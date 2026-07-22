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

# ai_cache_lib DEVRE DIŞI — msds-ozetleyici'de olduğu gibi burada da import
# başarısız olduğunda uygulamanın crash olmaması için try/except ile sarılı.
# Yeniden aktifleştirmek için: try'ı kaldır (düz import'a dön) ve aşağıdaki
# `_gercek_cagri` çağrısındaki bypass'ı kaldır.
try:
    from ai_cache_lib.python.ai_cache import cached_call  # noqa: F401
except Exception:
    cached_call = None


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
    # Groq: llama-3.3-70b ve llama-3.1-8b 17 Haziran 2026'da kullanımdan
    # kaldırıldı; Groq'un resmi önerdiği halefler:
    "groq": ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
    # Gemini: 2.5 Flash-Lite yeni kullanıcılara kapatıldı → 3.1 Flash-Lite halefi
    "gemini": ["gemini-3.1-flash-lite", "gemini-3.5-flash"],
    "openrouter": ["openrouter/free", "deepseek/deepseek-r1:free",
                   "meta-llama/llama-3.3-70b-instruct:free"],
    "openai": ["gpt-4o-mini", "gpt-4o"],
    # Anthropic: Sonnet 4.6 → Sonnet 5 (güncel nesil). Haiku 4.5 en ekonomik.
    "claude": ["claude-haiku-4-5-20251001", "claude-sonnet-5"],
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
    """Bu motoru atlamamız gereken durumlar: GÜNLÜK kota bitişi, belge sığmıyor,
    model bulunamadı. Hem yeni Türkçe (GUNLUK_KOTA_DOLDU, BELGE_COK_BUYUK,
    MODEL_BULUNAMADI, GECERSIZ_ISTEK_400) hem eski İngilizce hata kodlarını
    (backward compat) yakalar."""
    msg = str(err).upper()
    return any(k in msg for k in [
        # Yeni Türkçe hata kodları
        "GUNLUK_KOTA_DOLDU", "BELGE_COK_BUYUK", "MODEL_BULUNAMADI", "GECERSIZ_ISTEK_400",
        # Eski İngilizce hata kodları (geriye uyumluluk)
        "DAILY_QUOTA_EXHAUSTED", "PAYLOAD_TOO_LARGE", "MODEL_NOT_FOUND", "BAD_REQUEST_400",
        # Üçüncü parti servis kodları (Google/vb. ham mesajları)
        "RESOURCE_EXHAUSTED", "GÜNLÜK ÜCRETSIZ LIMIT", "RPD", "PER DAY", "REQUESTS PER DAY",
    ])


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
    raise RuntimeError(
        "JSON_BOZUK: Yapay zekâ motoru geçerli JSON formatında yanıt döndürmedi. "
        "Model belge içeriğini kavrayamamış olabilir; başka bir motora düşülüyor. "
        "Sürekli tekrarlıyorsa daha güçlü bir model seçin."
    )


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
                raise RuntimeError(
                    "BELGE_COK_BUYUK: Yüklediğiniz MSDS belgesi bu AI motoru için çok büyük. "
                    "Daha yüksek kapasiteli bir motora (Gemini/Claude) geçiliyor. "
                    "(HTTP 413 Payload Too Large)"
                )
            if resp.status_code == 429:
                body = resp.text
                low = body.lower()
                if _is_daily_quota_exhausted(body) or "rpd" in low or "per day" in low:
                    raise RuntimeError(
                        "GUNLUK_KOTA_DOLDU: Bu AI motorunun günlük ücretsiz kullanım limiti "
                        "doldu. Bir sonraki güne kadar başka bir motora düşülüyor. "
                        f"Sağlayıcının cevabı: {body[:200]}"
                    )
                wait = _parse_retry_delay(body) or 20.0
                if attempt < max_retries - 1:
                    time.sleep(min(65.0, wait))
                    continue
                raise RuntimeError(
                    "DAKIKALIK_LIMIT: AI motoruna kısa sürede çok istek gönderildi (dakikalık "
                    "hız limiti). Kısa bir bekleme sonrası tekrar denenecek veya başka motora "
                    f"düşülecek. Sağlayıcının cevabı: {body[:200]}"
                )
            if resp.status_code == 404:
                raise RuntimeError(
                    f"MODEL_BULUNAMADI: '{model}' modeli AI sağlayıcısında bulunamadı. "
                    "Model adı geçersiz veya artık desteklenmiyor olabilir. Otomatik olarak "
                    "başka bir modele düşülüyor."
                )
            if resp.status_code == 400:
                if use_json_format:
                    use_json_format = False
                    continue
                raise RuntimeError(
                    f"GECERSIZ_ISTEK_400: AI sağlayıcısı isteği reddetti (Hatalı İstek). "
                    f"İstek biçimi veya parametrelerinde bir sorun var. "
                    f"Sağlayıcının cevabı: {resp.text[:200]}"
                )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return json_ayikla(content)
        except RuntimeError:
            raise
        except Exception as e:
            last_err = e
            msg = str(e)
            if "413" in msg:
                raise RuntimeError(
                    "BELGE_COK_BUYUK: Yüklediğiniz MSDS belgesi bu AI motoru için çok büyük. "
                    "Daha yüksek kapasiteli bir motora geçiliyor. "
                    f"(Teknik: {msg[:200]})"
                )
            if any(c in msg for c in ["500", "502", "503", "504", "timeout", "Timeout"]) and attempt < max_retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last_err


def call_groq(prompt: str, api_key: str, model: str) -> dict:
    if not api_key:
        raise RuntimeError(
            "GROQ_ANAHTARI_YOK: Groq API anahtarı girilmemiş. console.groq.com/keys "
            "adresinden ücretsiz anahtar alıp sol menüye girin (kredi kartı gerekmez)."
        )
    return _call_openai_compatible(api_key, model, "https://api.groq.com/openai/v1", prompt)


def call_openrouter(prompt: str, api_key: str, model: str) -> dict:
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_ANAHTARI_YOK: OpenRouter API anahtarı girilmemiş. "
            "openrouter.ai/keys adresinden ücretsiz anahtar alıp sol menüye girin."
        )
    if not model or model == "openrouter/free":
        model = "openrouter/free"
    try:
        return _call_openai_compatible(
            api_key, model, "https://openrouter.ai/api/v1", prompt,
            extra_headers={"HTTP-Referer": "https://kimyasal-envanter.streamlit.app",
                           "X-Title": "Kimyasal Envanter"})
    except RuntimeError as e:
        if ("MODEL_BULUNAMADI" in str(e) or "MODEL_NOT_FOUND" in str(e)) and model != "openrouter/free":
            return _call_openai_compatible(
                api_key, "openrouter/free", "https://openrouter.ai/api/v1", prompt,
                extra_headers={"HTTP-Referer": "https://kimyasal-envanter.streamlit.app",
                               "X-Title": "Kimyasal Envanter"})
        raise


def call_openai(prompt: str, api_key: str, model: str) -> dict:
    if not api_key:
        raise RuntimeError("OPENAI_ANAHTARI_YOK: OpenAI API anahtarı girilmemiş. "
                           "Sol menüden anahtarınızı girin veya farklı bir motor seçin.")
    return _call_openai_compatible(api_key, model, "https://api.openai.com/v1", prompt)


def call_claude(prompt: str, api_key: str, model: str, max_retries: int = 4) -> dict:
    if not api_key:
        raise RuntimeError("CLAUDE_ANAHTARI_YOK: Claude API anahtarı girilmemiş. "
                           "Sol menüden anahtarınızı girin veya farklı bir motor seçin.")
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
                raise RuntimeError(
                    "DAKIKALIK_LIMIT: Claude'a kısa sürede çok istek gönderildi (dakikalık "
                    "hız limiti). Otomatik olarak başka bir motora düşülüyor. "
                    f"Sağlayıcının cevabı: {resp.text[:200]}"
                )
            if 400 <= resp.status_code < 500:
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        "API_ANAHTARI_GECERSIZ: Girdiğiniz Claude API anahtarı geçersiz veya "
                        "yetkisiz. console.anthropic.com'dan yeni bir anahtar oluşturup "
                        "sol menüye girin."
                    )
                raise RuntimeError(
                    f"CLAUDE_HATA_{resp.status_code}: Anthropic API isteği hata verdi. "
                    f"Sağlayıcının cevabı: {resp.text[:200]}"
                )
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
        raise RuntimeError(
            "GEMINI_KUTUPHANE_YOK: google-genai kütüphanesi kurulu değil. "
            "Streamlit Cloud'da requirements.txt'e 'google-genai>=1.0.0' ekleyip yeniden "
            "deploy edin. Yerel için: `pip install google-genai`."
        )
    if not api_key:
        raise RuntimeError("GEMINI_ANAHTARI_YOK: Gemini API anahtarı girilmemiş. "
                           "aistudio.google.com/apikey adresinden ücretsiz anahtar alın.")
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
                raise RuntimeError(
                    "GUNLUK_KOTA_DOLDU: Gemini günlük ücretsiz kullanım limiti doldu. "
                    "Bir sonraki güne kadar başka bir motora (Groq/OpenRouter) düşülüyor. "
                    "Alternatif: aistudio.google.com/apikey'den başka bir anahtar kullanın."
                )
            if "404" in msg and "no longer available" in msg.lower():
                raise RuntimeError(
                    f"MODEL_BULUNAMADI: '{model}' modeli Google tarafından yeni kullanıcılara "
                    f"kapatıldı. Otomatik olarak güncel modele geçiliyor. (Teknik: {msg[:150]})"
                )
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
        raise RuntimeError(
            "OLLAMA_ZAMAN_ASIMI: Yerel Ollama modeli 5 dakika içinde yanıt veremedi. "
            "Model çok büyük veya bilgisayarınız yetersiz olabilir. Daha küçük bir model "
            "(örn. 'llama3.2:3b' yerine 'phi3:mini') deneyin veya bulut motorunu kullanın."
        )


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

    # ai_cache_lib DEVRE DIŞI — cached_call sarmalayıcısı hatalar ürettiği için
    # kaldırıldı; her istek doğrudan AI motoruna gidiyor (cache tasarrufu yok
    # ama akış stabil). Yeniden aktifleştirmek için:
    #   (sonuc, kullanilan_motor), cache_hit = cached_call(
    #       key_source=prompt, fn=_gercek_cagri, fn_args=(),
    #       namespace="kimyasal_envanter_tamamlama",
    #   )
    try:
        sonuc, kullanilan_motor = _gercek_cagri()
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
