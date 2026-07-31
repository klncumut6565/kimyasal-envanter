# -*- coding: utf-8 -*-
"""ELLE GEÇERSİZ KILMA LİSTESİ — "Fonksiyonu" sütunu.

NE İŞE YARAR
------------
Bazı MSDS'lerde Bölüm 1.2 onlarca kullanım alanını tek paragrafta sayar
(özellikle sanayi gazları). Otomatik kırpma ilk maddeyi alır, ama ilk madde
her zaman ürünü en iyi temsil eden madde olmayabilir. Örnek — OKSİJEN:

    "Uzay gemilerinde hidrojen ile birlikte yakıt olarak; Metallerin
     kesimi, kaynağı, sertleşmesi işlemlerinde; ... "

Burada ilk madde "uzay gemilerinde yakıt", oysa envanterde görülmesi
gereken "Metallerin kesimi, kaynağı, sertleşmesi işlemlerinde".
Bu bir uzmanlık kararıdır; hiçbir otomatik kural veremez.

ÖNCELİK SIRASI (yüksekten düşüğe)
---------------------------------
  1. Bu liste (elle, kesin)
  2. AI seçimi   -- Bölüm 1.2'deki maddelerden en temsil edicisini BİREBİR
                    seçer; seçtiği metin belgede geçmiyorsa reddedilir
  3. Otomatik kırpma -- ilk madde
  4. "-"

NASIL EKLENİR
-------------
Anahtar: kimyasal adı (büyük/küçük harf, Türkçe karakter ve boşluk farkı
önemsizdir). Değer: hücreye yazılacak metin.

    "OKSİJEN": "Metallerin kesimi, kaynağı, sertleşmesi işlemlerinde",

Eşleşme önce TAM ad üzerinden, bulunamazsa "adı içeriyor mu" şeklinde
denenir; böylece "OKSİJEN (BASINÇLI GAZ HALİNDE)" da yakalanır.
"""

import re

FONKSIYON_OZEL = {
    # ── Sanayi gazları ──
    "OKSİJEN": "Metallerin kesimi, kaynağı, sertleşmesi işlemlerinde",
    "ARGON": "Gaz altı kaynağında koruyucu gaz",

    # Buraya yeni satır eklemek için:
    #   "KİMYASAL ADI": "Hücreye yazılacak fonksiyon metni",
}


def _norm(s) -> str:
    """Türkçe duyarlı normalizasyon — büyük/küçük harf, aksan, noktalama
    ve boşluk farklarını eleyip ad karşılaştırmasını güvenilir kılar."""
    s = str(s or "").replace("\xa0", " ")
    for a, b in (("İ", "i"), ("I", "i"), ("ı", "i"), ("Ş", "s"), ("ş", "s"),
                 ("Ğ", "g"), ("ğ", "g"), ("Ü", "u"), ("ü", "u"),
                 ("Ö", "o"), ("ö", "o"), ("Ç", "c"), ("ç", "c")):
        s = s.replace(a, b)
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# Normalize edilmiş anahtarlar (her çağrıda yeniden hesaplanmasın)
_NORM_LISTE = {_norm(k): v for k, v in FONKSIYON_OZEL.items()}


def fonksiyon_ozel_bul(kimyasal_adi):
    """Verilen kimyasal adı için elle tanımlanmış fonksiyon metnini döner.
    Tanımlı değilse None."""
    ad = _norm(kimyasal_adi)
    if not ad:
        return None
    # 1) Tam eşleşme
    if ad in _NORM_LISTE:
        return _NORM_LISTE[ad]
    # 2) Ad, listedeki bir anahtarı KELİME olarak içeriyor mu?
    #    ("oksijen basincli gaz halinde" -> "oksijen")
    for anahtar, deger in _NORM_LISTE.items():
        if re.search(rf"\b{re.escape(anahtar)}\b", ad):
            return deger
    return None
