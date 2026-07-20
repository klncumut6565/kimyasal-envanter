"""
ai_destek.py
------------
AI DESTEKLİ TAMAMLAYICI KATMAN (opsiyonel, regex'in YEDEĞİ — birincil değil)

Umut'un tasarımı:
  1. extractor.py'deki regex tabanlı çıkarım HER ZAMAN önce çalışır ve aynen
     çalışmaya devam eder (bu dosya import edilmese/kullanılmasa bile davranış
     değişmez).
  2. Regex bir alanı BOŞ bıraktıysa (None/""), VE kullanıcı en az bir AI
     anahtarı girdiyse, SADECE o boş alan(lar) için AI'ya TEK bir istek
     gönderilir. Regex'in doldurduğu alanlara asla dokunulmaz/üzerine
     yazılmaz — yanlış olsa bile.
  3. 300-400 PDF'lik toplu taramalarda token tükenmesini önlemek için:
       - Belge başına EN FAZLA 1 AI isteği (alan başına değil).
       - ai_cache_lib ile aynı PDF ikinci kez taranırsa (hash eşleşirse)
         hiç istek gitmez, diskteki sonuç kullanılır.
       - Hiçbir alan boş değilse AI'ya HİÇ gidilmez (0 token).

Motor zinciri ve failover mantığı msds-ozetleyici ile birebir aynıdır
(bilinçli tercih: Umut iki uygulamada da aynı davranışı istedi):
    Groq → Gemini → OpenRouter → OpenAI → Claude → Ollama
"""

from __future__ import annotations

import json
import re
import time

import requests

try:
    from google import genai
    from google.genai import types as genai_types
    GEMINI_SDK_OK = True
except ImportError:
    GEMINI_SDK_OK = False

from ai_cache_lib.python.ai_cache import cached_call


# ── Eksik alan açıklamaları (AI'ya SADECE bunlar sorulur) ─────────────────
# key: extractor.py'deki sözlük anahtarıyla BİREBİR aynı olmalı (matcher.py
# bu anahtarları doğrudan okuyor).
ALAN_ACIKLAMALARI = {
    "tedarikci": "Tedarikçi/üretici firma adı (genelde Bölüm 1.3 'Tedarikçi' veya 'Firma Adı')",
    "fonksiyon": "Ürünün kullanım amacı / fonksiyonu (Bölüm 1.2 'Belirlenmiş Kullanımlar')",
    "cas_no": "CAS numarası (Bölüm 3), format: 000-00-0 (birden fazla bileşen varsa ana/ilk bileşeninki)",
    "h_kodlari": "H kodları (Bölüm 2), virgülle ayrılmış liste, örn: 'H302, H315, H319'",
    "tehlikeli_tehlikesiz": "Ürün 'Tehlikeli' mi 'Tehlikesiz' mi (Bölüm 2 sınıflandırmasına göre, SADECE bu iki değerden biri)",
    "tehlike_etiketi": "Uyarı/işaret kelimesi (Bölüm 2.2), SADECE 'Tehlike' veya 'Dikkat'",
    "revize_tarihi": "Belgenin revizyon/güncelleme/yayın tarihi (genelde Bölüm 16 veya belge başlığında), format GG.AA.YYYY",
}

ENGINE_LABELS = {
    "groq": "⚡ Groq",
    "gemini": "☁️ Gemini",
    "openrouter": "🌐 OpenRouter",
    "openai": "🤖 OpenAI",
    "claude": "🧠 Claude",
    "ollama": "🖥️ Ollama (yerel)",
}
# msds-ozetleyici ile BİREBİR aynı sıra (bilinçli tercih, Umut'un talimatı).
FAILOVER_ORDER = ["groq", "gemini", "openrouter", "openai", "claude", "ollama"]

MODEL_FALLBACKS = {
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    "gemini": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
    "openrouter": ["openrouter/free", "deepseek/deepseek-r1:free",
                   "meta-llama/llama-3.3-70b-instruct:free"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    "claude": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
    "ollama": [],
}


def _model_chain(engine: str, primary: str) -> list:
    chain = [primary] if primary else []
    for mdl in MODEL_FALLBACKS.get(engine, []):
        if mdl and mdl not in chain:
            chain.append(mdl)
    return chain


def _is_daily_quota_exhausted(msg: str) -> bool:
    u = msg.upper()
    return "PERDAY" in u.replace("_", "").replace(" ", "") or "REQUESTSPERDAY" in u.replace("_", "").replace(" ", "") \
        or "GENERATEREQUESTSPERDAY" in u.replace("_", "").replace(" ", "") \
        or "FREE_TIER_REQUESTS" in u or "GENERATE_CONTENT_FREE_TIER" in u


def _is_daily_exhausted_error(err: Exception) -> bool:
    msg = str(err).upper()
    return any(k in msg for k in ["DAILY_QUOTA_EXHAUSTED", "RESOURCE_EXHAUSTED", "PAYLOAD_TOO_LARGE",
                                  "MODEL_NOT_FOUND", "BAD_REQUEST_400",
                                  "GÜNLÜK ÜCRETSIZ LIMIT", "RPD", "PER DAY", "REQUESTS PER DAY"])


def _parse_retry_delay(msg: str) -> float:
    m = re.search(r"retry in ([\d.]+)s", msg) or re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", msg)
    if m:
        try:
            return min(60.0, float(m.group(1)) + 1)
        except ValueError:
            pass
    return 0.0


def json_ayikla(content) -> dict:
    """AI yanıtından JSON çıkarır (msds-ozetleyici ile aynı sağlamlaştırma mantığı)."""
    raw = re.sub(r"```(?:json)?", "", str(content or "")).strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        raw = m.group(0)
    else:
        i = raw.find("{")
        if i >= 0:
            raw = raw[i:]

    def _dengele(s):
        if s.count('"') % 2 == 1:
            s += '"'
        s += "]" * max(0, s.count("[") - s.count("]"))
        s += "}" * max(0, s.count("{") - s.count("}"))
        return s

    onarimli = raw.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")
    onarimli = re.sub(r",\s*([}\]])", r"\1", onarimli)
    onarimli = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", onarimli)

    for aday in (raw, onarimli, _dengele(onarimli)):
        try:
            return json.loads(aday)
        except json.JSONDecodeError:
            continue
    raise RuntimeError("JSON_BOZUK: Yapay zekâ geçerli JSON döndürmedi.")


def _build_tamamlama_prompt(eksik_alanlar: list) -> str:
    """Sadece BELİRLİ eksik alanları soran küçük prompt — tüm MSDS şemasını
    değil, yalnızca ihtiyaç duyulan alanları istediği için hem daha az çıktı
    tokeni harcar hem de model dikkatini dağıtmaz."""
    aciklamalar = "\n".join(
        f'- "{alan}": {ALAN_ACIKLAMALARI[alan]}' for alan in eksik_alanlar if alan in ALAN_ACIKLAMALARI
    )
    alan_listesi = ", ".join(f'"{a}"' for a in eksik_alanlar if a in ALAN_ACIKLAMALARI)
    return (
        "Bu bir MSDS/SDS (Malzeme Güvenlik Bilgi Formu) belgesidir. Aşağıdaki metni "
        "analiz et ve SADECE şu alanları çıkar:\n\n"
        f"{aciklamalar}\n\n"
        f"SADECE geçerli bir JSON nesnesi döndür, başka hiçbir metin yazma. "
        f"Anahtarlar TAM OLARAK şunlar olmalı: {alan_listesi}. "
        "Belgede bir alan gerçekten bulunamıyorsa değerini null yap (uydurma).\n\n"
        "BELGE METNİ:\n{text}"
    )


def _call_openai_compatible(api_key: str, model: str, base_url: str,
                             prompt: str, max_retries: int = 4, extra_headers: dict = None) -> dict:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    use_json_format = True

    def _payload():
        p = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Sen bir MSDS/SDS belge analiz uzmanısın. SADECE geçerli JSON döndür."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        if use_json_format:
            p["response_format"] = {"type": "json_object"}
        return p

    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=_payload(), timeout=120)
            if resp.status_code == 413:
                raise RuntimeError("PAYLOAD_TOO_LARGE: Belge bu motor için çok büyük.")
            if resp.status_code == 429:
                body = resp.text
                low = body.lower()
                if _is_daily_quota_exhausted(body) or "rpd" in low or "per day" in low:
                    raise RuntimeError("DAILY_QUOTA_EXHAUSTED: " + body[:300])
                wait = _parse_retry_delay(body) or 20.0
                if attempt < max_retries - 1:
                    time.sleep(min(65.0, wait))
                    continue
                raise RuntimeError("RATE_LIMIT_MINUTE: " + body[:200])
            if resp.status_code == 404:
                raise RuntimeError(f"MODEL_NOT_FOUND: '{model}' modeli bulunamadı.")
            if resp.status_code == 400:
                if use_json_format:
                    use_json_format = False
                    continue
                raise RuntimeError(f"BAD_REQUEST_400: {resp.text[:200]}")
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json_ayikla(content)
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            msg = str(e)
            if "413" in msg:
                raise RuntimeError("PAYLOAD_TOO_LARGE: " + msg)
            if any(c in msg for c in ["500", "502", "503", "504", "timeout", "Timeout"]) and attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last_err


def call_groq(prompt: str, api_key: str, model: str) -> dict:
    if not api_key:
        raise RuntimeError("Groq API anahtarı girilmemiş.")
    return _call_openai_compatible(api_key, model, "https://api.groq.com/openai/v1", prompt)


def call_openrouter(prompt: str, api_key: str, model: str) -> dict:
    if not api_key:
        raise RuntimeError("OpenRouter API anahtarı girilmemiş.")
    if not model or model == "openrouter/free":
        model = "openrouter/free"
    try:
        return _call_openai_compatible(
            api_key, model, "https://openrouter.ai/api/v1", prompt,
            extra_headers={"HTTP-Referer": "https://kimyasal-envanter.streamlit.app",
                           "X-Title": "Kimyasal Envanter"})
    except RuntimeError as e:
        if "MODEL_NOT_FOUND" in str(e) and model != "openrouter/free":
            return _call_openai_compatible(
                api_key, "openrouter/free", "https://openrouter.ai/api/v1", prompt,
                extra_headers={"HTTP-Referer": "https://kimyasal-envanter.streamlit.app",
                               "X-Title": "Kimyasal Envanter"})
        raise


def call_openai(prompt: str, api_key: str, model: str) -> dict:
    if not api_key:
        raise RuntimeError("OpenAI API anahtarı girilmemiş.")
    return _call_openai_compatible(api_key, model, "https://api.openai.com/v1", prompt)


def call_claude(prompt: str, api_key: str, model: str, max_retries: int = 4) -> dict:
    if not api_key:
        raise RuntimeError("Claude API anahtarı girilmemiş.")
    url = "https://api.anthropic.com/v1/messages"
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    payload = {
        "model": model,
        "max_tokens": 1024,
        "temperature": 0.1,
        "system": "Sen bir MSDS/SDS belge analiz uzmanısın. SADECE geçerli JSON döndür.",
        "messages": [{"role": "user", "content": prompt}],
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            if resp.status_code == 429:
                if attempt < max_retries - 1:
                    time.sleep(20.0)
                    continue
                raise RuntimeError("RATE_LIMIT_MINUTE: " + resp.text[:200])
            if 400 <= resp.status_code < 500:
                if resp.status_code in (401, 403):
                    raise RuntimeError("API_KEY_INVALID: Claude anahtarı geçersiz/yetkisiz.")
                raise RuntimeError(f"CLAUDE_{resp.status_code}: {resp.text[:200]}")
            resp.raise_for_status()
            data = resp.json()
            content = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            return json_ayikla(content)
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            if any(c in str(e) for c in ["500", "502", "503", "504", "timeout"]) and attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last_err


def call_gemini(prompt: str, api_key: str, model: str, max_retries: int = 4) -> dict:
    if not GEMINI_SDK_OK:
        raise RuntimeError("google-genai kütüphanesi kurulu değil. `pip install google-genai`")
    if not api_key:
        raise RuntimeError("Gemini API anahtarı girilmemiş.")
    client = genai.Client(api_key=api_key)
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt,
                config=genai_types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json"),
            )
            return json_ayikla((resp.text or "{}").strip())
        except Exception as e:
            last_err = e
            msg = str(e)
            if "429" in msg and _is_daily_quota_exhausted(msg):
                raise RuntimeError("DAILY_QUOTA_EXHAUSTED: Gemini günlük ücretsiz limiti doldu.")
            if any(c in msg for c in ["429", "503", "500"]) and attempt < max_retries - 1:
                time.sleep(_parse_retry_delay(msg) or (3 * (attempt + 1)))
                continue
            raise
    raise last_err


def call_ollama(prompt: str, model: str, base_url: str) -> dict:
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json",
                  "options": {"temperature": 0.1, "num_ctx": 8192, "num_predict": 500}},
            timeout=300,
        )
        resp.raise_for_status()
        return json_ayikla(resp.json().get("response", "{}"))
    except requests.exceptions.Timeout:
        raise RuntimeError("OLLAMA_TIMEOUT: Yerel model çok yavaş yanıt verdi.")


def _call_single_model(engine, model, prompt, ollama_url, keys):
    if engine == "gemini":
        return call_gemini(prompt, keys.get("gemini", ""), model)
    elif engine == "groq":
        return call_groq(prompt, keys.get("groq", ""), model)
    elif engine == "openrouter":
        return call_openrouter(prompt, keys.get("openrouter", ""), model)
    elif engine == "openai":
        return call_openai(prompt, keys.get("openai", ""), model)
    elif engine == "claude":
        return call_claude(prompt, keys.get("claude", ""), model)
    else:
        return call_ollama(prompt, model, ollama_url)


def _call_ai(prompt: str, engine: str, model: str, ollama_url: str, keys: dict) -> dict:
    """Motorun model zincirini sırayla dener (msds-ozetleyici ile aynı mantık)."""
    models_to_try = _model_chain(engine, model) or [model]
    data, last_err = None, None
    for i, mdl in enumerate(models_to_try):
        try:
            data = _call_single_model(engine, mdl, prompt, ollama_url, keys)
            break
        except Exception as e:
            last_err = e
            if _is_daily_exhausted_error(e) and i < len(models_to_try) - 1:
                continue
            raise
    if data is None:
        raise last_err or RuntimeError("Model denenemedi.")
    return data


def engine_available(eng: str, keys: dict, ollama_url: str) -> bool:
    if eng == "ollama":
        return bool(ollama_url)
    return bool(keys.get(eng))


def build_failover_chain(primary: str, keys: dict, ollama_url: str) -> list:
    chain = [primary] if primary and engine_available(primary, keys, ollama_url) else []
    for eng in FAILOVER_ORDER:
        if eng != primary and engine_available(eng, keys, ollama_url) and eng not in chain:
            chain.append(eng)
    return chain


def tamamla_eksik_alanlar(text: str, mevcut: dict, chain: list, models: dict, keys: dict,
                           ollama_url: str = "") -> dict:
    """extractor.py'nin doldurduğu 'mevcut' sözlüğünü alır, boş kalan alanlar için
    (varsa) AI zincirini dener, SADECE o alanları içeren bir güncelleme sözlüğü
    döndürür. Regex'in doldurduğu hiçbir alana dokunmaz. Hiçbir motor
    yapılandırılmamışsa (chain boşsa) veya boş alan yoksa AI'ya hiç gitmez.

    Aynı PDF metni ikinci kez taranırsa (cache hit) hiç API isteği gitmez —
    300-400'lük toplu taramalarda tekrar tekrar aynı belge işlenirse token
    tasarrufu sağlar."""
    eksikler = [k for k in ALAN_ACIKLAMALARI if not mevcut.get(k)]
    if not eksikler or not chain:
        return {}

    prompt = _build_tamamlama_prompt(eksikler).format(text=text)

    def _gercek_cagri():
        last_err = None
        for eng in chain:
            try:
                sonuc = _call_ai(prompt, eng, models.get(eng, ""), ollama_url, keys)
                return sonuc, eng
            except Exception as e:
                last_err = e
                continue
        raise last_err or RuntimeError("Hiçbir AI motoru yanıt veremedi.")

    try:
        (sonuc, kullanilan_motor), cache_hit = cached_call(
            key_source=prompt,
            fn=_gercek_cagri,
            fn_args=(),
            namespace="kimyasal_envanter_tamamlama",
        )
    except Exception:
        # Hiçbir motor çalışmadıysa (kota bitmiş, anahtar geçersiz vb.) sessizce
        # vazgeç — regex'in bulduğu alanlar kullanıcıya yine sunulur, program çökmez.
        return {}

    if not isinstance(sonuc, dict):
        return {}

    # Güvenlik: sadece GERÇEKTEN boş olan alanları doldur, "null" dönenleri atla.
    guncelleme = {}
    for k in eksikler:
        v = sonuc.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "belirsiz"):
            guncelleme[k] = v.strip()
    return guncelleme
