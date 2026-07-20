"""
ai_cache.py
-----------
Her projene (Kimyasal Envanter, MSDS ozetleme araci, ADR Transport Pro vb.)
kopyalayip kullanabilecegin, tek dosyalik token tasarrufu modulu.

MANTIK:
  Dosya (PDF/metin) -> SHA256 hash -> daha once bu hash icin sonuc uretildi mi?
    EVET -> diskten oku, API'ye HIC istek gitmez, 0 token
    HAYIR -> API'ye gonder, sonucu hash ile diske kaydet

Herhangi bir sunucu, Redis, veritabani gerektirmez.
Sonuclar proje klasorunde .ai_cache/ altinda JSON olarak tutulur.
Bu klasoru .gitignore'a eklemen onerilir (repo sisecek).

KULLANIM (herhangi bir projede):

    from ai_cache import cached_call
    import openai  # veya google.generativeai, veya baska bir client

    def gercek_api_cagrisi(pdf_metni: str) -> dict:
        # Burada asil OpenAI/Gemini/Claude cagrini yapiyorsun
        response = client.chat.completions.create(...)
        return {"sonuc": response.choices[0].message.content}

    sonuc, cache_hit = cached_call(
        key_source=pdf_metni,          # veya dosya yolu, veya pdf bytes
        fn=gercek_api_cagrisi,
        fn_args=(pdf_metni,),
    )

    if cache_hit:
        print("Cache'ten geldi, 0 token harcandi")
    else:
        print("API'ye gidildi, sonuc cache'e yazildi")
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Tuple

# Cache'in tutulacagi klasor (proje bazinda degisebilir)
CACHE_DIR = Path(os.environ.get("AI_CACHE_DIR", ".ai_cache"))


def _hash_of(data) -> str:
    """Metin, bytes veya dosya yolu alir; SHA256 hash dondurur."""
    if isinstance(data, (str, Path)) and os.path.isfile(str(data)):
        # Dosya yolu verilmisse dosya icerigini hashle (PDF gibi)
        h = hashlib.sha256()
        with open(data, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    if isinstance(data, str):
        return hashlib.sha256(data.encode("utf-8")).hexdigest()
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    # Sozluk/liste gibi yapilar icin deterministik JSON hashi
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _cache_path(cache_key: str, namespace: str) -> Path:
    ns_dir = CACHE_DIR / namespace
    ns_dir.mkdir(parents=True, exist_ok=True)
    return ns_dir / f"{cache_key}.json"


def cached_call(
    key_source,
    fn: Callable[..., Any],
    fn_args: tuple = (),
    fn_kwargs: dict | None = None,
    namespace: str = "default",
    ttl_seconds: int | None = None,
) -> Tuple[Any, bool]:
    """
    key_source : hash'i alinacak veri (metin / bytes / dosya yolu / dict)
    fn         : cache'te yoksa cagrilacak gercek fonksiyon (OpenAI/Gemini cagrisi)
    fn_args/fn_kwargs : fn'e gecirilecek argumanlar
    namespace  : ayni cache klasoru altinda projeleri/is turlerini ayirmak icin
                 (orn. "msds_extract", "adr_classification")
    ttl_seconds: istersen cache'e son kullanma suresi ekleyebilirsin (None = sinirsiz)

    Donus: (sonuc, cache_hit_mi)
    """
    fn_kwargs = fn_kwargs or {}
    key = _hash_of(key_source)
    path = _cache_path(key, namespace)

    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if ttl_seconds is None or (time.time() - cached["_cached_at"]) < ttl_seconds:
                return cached["result"], True
        except (json.JSONDecodeError, KeyError):
            pass  # bozuk cache dosyasi, yeniden uret

    result = fn(*fn_args, **fn_kwargs)

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"_cached_at": time.time(), "result": result}, f, ensure_ascii=False, indent=2)

    return result, False


def cache_stats(namespace: str = "default") -> dict:
    """Ne kadar dosyanin cache'lendigini ve toplam boyutunu gosterir."""
    ns_dir = CACHE_DIR / namespace
    if not ns_dir.exists():
        return {"adet": 0, "boyut_kb": 0}
    files = list(ns_dir.glob("*.json"))
    total_kb = sum(f.stat().st_size for f in files) / 1024
    return {"adet": len(files), "boyut_kb": round(total_kb, 1)}


def clear_cache(namespace: str | None = None):
    """Cache'i temizler. namespace verilmezse hepsini siler."""
    import shutil

    target = CACHE_DIR / namespace if namespace else CACHE_DIR
    if target.exists():
        shutil.rmtree(target)
