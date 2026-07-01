"""
MSDS PDF -> Bölüm 14 (Taşıma Bilgileri) -> ADR satırı çıkarma modülü
"""
import re
import pdfplumber

# Dosya adlarında/öneri isimlerinde sık görülen, gerçek kimyasal/ürün adının
# parçası olmayan ekler. Versiyon 2'de envanterdeki isimle eşleştirme
# yaparken bunların temizlenmesi kritik -- yoksa "Achiprint HV-TR-SDS rev 7"
# ile envanterdeki sade "Achiprint HV" hiç eşleşmez.
_JUNK_NAME_PATTERNS = [
    r"\bTR[\s_-]*SDS\b",  # bileşik kalıp, "SDS" tek başına silinmeden önce eşleşmeli
    r"\bMSDS\b", r"\bSDS\b", r"\bGBF\b", r"\bSGBF\b",
    r"\brev(?:izyon)?\.?\s*\d+\b",
    r"\bCLP\b", r"\bT[üu]rk[çc]e\b", r"\bT[üu]rkiye\b",
    r"\(\s*\d+[\s-]\d+[\s-]\d+\s*\)",  # CAS no parantez içinde kalmış olabilir
    r"\b\d{6,10}\b",  # "...CLP Türkçe Türkiye 12292025" gibi tarih kodları
]


def clean_product_name(name: str) -> str:
    """Dosya adından/öneri isminden, gerçek ürün adı olmayan ekleri
    (MSDS, SDS, 'rev 7', 'CLP Türkçe Türkiye 12292025' vb.) temizler.
    Hem kullanıcıya gösterilecek öneri ismi hem de Versiyon 2'deki
    envanter eşleştirmesi için kullanılır."""
    if not name:
        return ""
    s = str(name).replace("\xa0", " ")
    s = re.sub(r"[_]+", " ", s)  # önce alt çizgiyi boşluğa çevir (\b sınırları doğru çalışsın)
    for p in _JUNK_NAME_PATTERNS:
        s = re.sub(p, " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*[-,]\s*$", "", s)  # sonda kalan tire/virgül
    s = re.sub(r"\s+", " ", s).strip(" -_,.")
    return s


def pdf_to_text(pdf_path: str) -> str:
    """PDF'in tüm metnini, tablo sütun hizalamasını koruyarak çıkarır.

    NOT: Önceden harici 'pdftotext' (poppler) komut satırı aracını
    kullanıyorduk; bu sadece Linux/Mac'te kurulu geliyordu ve Windows'ta
    "[WinError 2] Sistem belirtilen dosyayı bulamıyor" hatasına yol
    açıyordu. pdfplumber pip ile kurulduğu için tüm işletim sistemlerinde
    ek bir program kurmaya gerek kalmadan çalışır.

    Bazı PDF'ler bozuk/standart olmayan bir yapıya sahip olabilir (örn.
    hatalı xref tablosu) ve pdfplumber bunları açarken hata fırlatabilir.
    Bu durumda PyMuPDF (fitz) ile yedek bir deneme yapılır; o da
    başarısız olursa program ÇÖKMEZ, sadece bu PDF için boş metin
    döner (ilgili ürün otomatik olarak "manuel kontrol gerekli" olur).
    """
    try:
        parts = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text(layout=True) or "")
        return "\n".join(parts)
    except Exception:
        try:
            import fitz
            text_parts = []
            with fitz.open(pdf_path) as doc:
                for page in doc:
                    text_parts.append(page.get_text())
            return "\n".join(text_parts)
        except Exception:
            return ""


def extract_revize_tarihi(text: str):
    # Farklı üreticiler farklı etiketler kullanıyor:
    #  - "Revize Edildiği Tarih: ..."   (örn. Ashland şablonu)
    #  - "Revizyon tarihi: ..."         (örn. DyStar/Sera şablonu)
    #  - "Yeni düzenleme tarihi ..."    (örn. Eksoy/GBF şablonu)
    #  - "Yayın Tarihi :..."            (örn. Pentakim şablonu)
    # PDF font kodlaması bazen "ğ" gibi karakterleri boşluğa çeviriyor
    # ("Edildiği" -> "Edildi i"); bu yüzden ortadaki kısma sıkı bağlı değiliz.
    # "Reviz\w*" -> "Revize", "Revizyon", "Revizyonu" gibi tüm türevleri yakalar.
    #
    # Tarih değeri sadece sayısal ("12.02.2019") olabildiği gibi, Türkçe
    # ay adıyla yazılı ("12 Şubat 2019", örn. HABAŞ şablonu) da olabilir;
    # bu yüzden değer deseni her ikisini de kapsıyor.
    tarih_degeri = r"(\d{1,2}[./]\d{1,2}[./]\d{2,4}|\d{1,2}\s+\w+\s+\d{4})"
    patterns = [
        r"Reviz\w*\b.{0,15}[Tt]arih\w*\s*:?\s*" + tarih_degeri,
        r"Yeni\s+düzen\w*\s+tarihi\s*:?\s*" + tarih_degeri,
        r"Yay[ıi]n\s*[Tt]arihi\s*:?\s*" + tarih_degeri,
        r"\bRevision\s*:?\s*" + tarih_degeri,  # İngilizce MSDS
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def extract_suggested_name(text: str):
    # Çeşitli MSDS formatlarında "Ürün ismi" / "Ürün adı" / "Ticari ismi" /
    # "Ticari isim" / "Ticari adı" / "Ticari Adı" etiketleri kullanılabiliyor
    patterns = [
        r"Ürün ismi\s+(.+)",
        r"Ticari isim\w*\s*:?\s*(.+)",
        r"Ticari ad[ıi]\s*:?\s*(.+)",
        r"Ürün ad[ıi]\s*:?\s*(.+)",
        r"Product\s*Name\s*:?\s*(.+)",  # İngilizce MSDS
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"™|®", "", name).strip()
            if name:
                return name
    return None


def find_section_text(text: str, section_no: int, next_section_no: int = None):
    """find_section14_text'in genel hâli -- herhangi bir bölüm numarasının
    metnini izole eder. Hem 'N.' hem 'BÖLÜM N:' hem 'KISIM N :' hem de
    noktasız 'N Başlık' stillerini tanır (üreticiye göre değişiyor)."""
    pattern = (rf"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*{section_no}"
               r"\s*(?:[.:]\s+|\s+(?=[A-ZÇĞİÖŞÜ]))")
    m_start = re.search(pattern, text)
    if not m_start:
        return None
    start = m_start.start()
    end_no = next_section_no if next_section_no else section_no + 1
    end_pattern = (rf"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*{end_no}"
                   r"\s*(?:[.:]\s+|\s+(?=[A-ZÇĞİÖŞÜ]))")
    m_end = re.search(end_pattern, text[start:])
    end = start + m_end.start() if m_end else min(len(text), start + 4000)
    return text[start:end]


_COMPANY_SUFFIX = r"(A\.?Ş\.?|Ltd\.?\s*Şti\.?|GmbH|Sanayi|San\.|Ticaret|Tic\.|Kimya|Inc\.|Corp\.|S\.A\.)"


def extract_tedarikci(text: str):
    """Bölüm 1.3'ten tedarikçi/üretici firma adını çıkarır."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    # "Firma Adı :" etiketi (örn. HABAŞ şablonu) -- bunu "Tedarikçi"
    # etiketinden ÖNCE deniyoruz çünkü "Tedarikçi" kelimesi genelde
    # "Tedarikçisinin Bilgileri" gibi bir başlığın içinde çekim ekiyle
    # geçer ve aşağıdaki "Tedarikçi" deseni o ekin devamını ("sinin
    # Bilgileri") yanlışlıkla firma adı diye yakalayabilir.
    m = re.search(r"Firma\s+Ad[ıi]\s*:?\s*\n?\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # "Tedarikçi" etiketi -- yalnızca kelime sınırında bittiğinde
    # ("Tedarikçi :" veya "Tedarikçi\n") eşleştiriyoruz; "Tedarikçisinin"
    # gibi bir çekim ekiyle devam ediyorsa bu, başlığın bir parçasıdır,
    # değer etiketi değildir.
    m = re.search(r"Tedarikçi\b(?!sinin|nin|si)\s*\n?\s*:?\s*([^\n]{3,90})", bolum1)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r"Produc\w*\s+Company\s*\n?\s*([^\n]{3,90})", bolum1, re.IGNORECASE)  # İngilizce MSDS
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r"1\.3[.\s][^\n]*\n+((?:[^\n]+\n+){0,4})", bolum1)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line and re.search(_COMPANY_SUFFIX, line, re.IGNORECASE):
                return line
    return None


def _esnek_desen(kelime: str) -> str:
    """Bir kelimeyi, içindeki ı/İ/ş/Ş/ğ/Ğ harfleri PDF font bozulmasıyla
    tamamen düşmüş olsa bile (örn. 'belirlenmiş' -> 'belirlenmi',
    'kullanımları' -> 'kullanmlar') eşleşecek bir regex'e çevirir. Diğer
    tüm harfler değişmeden (zorunlu) kalır.
    CHT gibi bazı şablonlar Ş/ş yerine U+0122/U+0121 (Ģ/ģ) üretir;
    bu bozulma da toleranslı şekilde ele alınır."""
    degisenler = {
        "ı": "ı?", "İ": "İ?",
        "ş": "[şĢģs]?", "Ş": "[ŞĢģs]?",
        "ğ": "ğ?", "Ğ": "Ğ?",
    }
    return "".join(degisenler.get(ch, re.escape(ch)) for ch in kelime)


def extract_fonksiyon(text: str):
    """Bölüm 1.2'den ürünün kullanım amacını/fonksiyonunu çıkarır."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    patterns = [
        r"(?m)^\s*" + _esnek_desen("Belirlenmiş kullanımlar") + r"\b\s*:?\s*\n?\s*([^\n]{3,80})",
        r"(?m)^\s*" + _esnek_desen("Kullanım alanı") + r"\b\s*:\s*([^\n]{3,80})",
        r"(?m)^\s*Kullanim\s*:\s*\n?\s*([^\n]{3,80})",
        r"(?m)^\s*Relevant\s+identified\s+uses\s*:?\s*([^\n]{3,80})",  # İngilizce MSDS
        # HABAŞ tarzı şablon: başlık satırın ortasında geçiyor ("1.2.
        # Madde veya Karışımın Belirlenmiş Kullanımları ve Tavsiye
        # Edilmeyen Kullanımları") ve değer doğrudan ALT satırda, ayrı
        # bir etiket/iki nokta olmadan başlıyor.
        r"(?i)Belirlenmi[şs]\s+[Kk]ullan[ıi]mlar[ıi]?\b[^\n]*\n\s*([^\n]{3,200})",
    ]
    for p in patterns:
        m = re.search(p, bolum1, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".")
            if val:
                return val
    return None


def extract_cas_no(text: str):
    """Bölüm 3'ten CAS numarasını çıkarır. Karışımlarda birden fazla
    bileşen olabileceğinden, etiketli ilk eşleşme (veya genel CAS
    deseninin ilk örneği -- tablo düzenli MSDS'ler için yedek) alınır."""
    bolum3 = find_section_text(text, 3, 4)
    if not bolum3:
        return None
    m = re.search(r"CAS\s*[-_.]?\s*[Nn]umaras[ıi]\s*:?\s*(\d{2,7}-\d{2}-\d)", bolum3)
    if m:
        return m.group(1)
    m = re.search(r"CAS[\s.-]*[Nn]o\.?\s*:?\s*(\d{2,7}-\d{2}-\d)", bolum3)
    if m:
        return m.group(1)
    m = re.search(r"\b(\d{2,7}-\d{2}-\d)\b", bolum3)  # tablo düzeni için genel yedek
    if m:
        return m.group(1)
    return None


def extract_h_kodlari(text: str):
    """Bölüm 2'den H kodlarını (H317, H318+H319 vb.) çıkarır, tekilleştirir."""
    bolum2 = find_section_text(text, 2, 3) or text
    kodlar = re.findall(r"\bH\d{3}(?:\+H\d{3})*\b", bolum2)
    seen = []
    for k in kodlar:
        if k not in seen:
            seen.append(k)
    return ", ".join(seen) if seen else None


def extract_uyari_kelimesi(text: str):
    """Bölüm 2.2'den Uyarı Kelimesi'ni (Tehlike/Dikkat) çıkarır."""
    bolum2 = find_section_text(text, 2, 3) or text
    m = re.search(r"Uyar[ıi]\s+[Kk]elimesi\s*:?\s*\n?\s*([^\n]{2,30})", bolum2)
    if m and m.group(1).strip():
        return m.group(1).strip()
    m = re.search(r"İşaret\s+[Kk]elime\w*\s*:?\s*\n?\s*([^\n]{2,30})", bolum2)
    if m and m.group(1).strip():
        return m.group(1).strip()
    # "İşaret Sözcüğü :" etiketi (örn. HABAŞ şablonu) -- "Kelime" yerine
    # eş anlamlı "Sözcük" kelimesi kullanılıyor.
    m = re.search(r"İşaret\s+[Ss]özc[üu][ğg][üu]\s*:?\s*\n?\s*([^\n]{2,30})", bolum2)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def extract_tehlikeli_tehlikesiz(text: str, h_kodlari):
    """H kodu bulunduysa 'Tehlikeli', Bölüm 2 açıkça sınıflandırılmamış
    diyorsa 'Tehlikesiz' döner; aksi halde belirsizdir (None)."""
    if h_kodlari:
        return "Tehlikeli"
    bolum2 = find_section_text(text, 2, 3) or text
    if re.search(r"zararl[ıi]\s+olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r", bolum2, re.IGNORECASE):
        return "Tehlikesiz"
    return None


def extract_full_info(pdf_path: str, text: str = None):
    """Bölüm 14 dışında, envanterin diğer sütunları için de Bölüm 1/2/3'ten
    bilgi çıkarır. extract_adr_info ile aynı metni tekrar okumamak için
    text önceden çıkarılmışsa parametre olarak verilebilir."""
    if text is None:
        text = pdf_to_text(pdf_path)
    h_kodlari = extract_h_kodlari(text)
    return {
        "tedarikci": extract_tedarikci(text),
        "fonksiyon": extract_fonksiyon(text),
        "cas_no": extract_cas_no(text),
        "h_kodlari": h_kodlari,
        "tehlikeli_tehlikesiz": extract_tehlikeli_tehlikesiz(text, h_kodlari),
        "tehlike_etiketi": extract_uyari_kelimesi(text),
    }


def find_section14_text(text: str):
    """Bölüm 14'ün başlangıcını ve bitişini bul.

    Başlık metnine (TAŞIMA/NAKLİYE vb.) güvenmiyoruz çünkü orijinal MSDS'lerde
    yazım hataları (örn. "Taşmacilik") veya format farklılıkları olabiliyor.
    Üreticiye göre başlık stili de değişebiliyor:
      - "14. Taşıma Bilgileri"        (örn. Ashland şablonu)
      - "BÖLÜM 14: Taşımacılık bilgileri"  (örn. Eksoy/GBF şablonu)
      - "14 TAŞIMACILIK BİLGİSİ"      (noktasız, örn. SERİN KİMYA şablonu)
    Bu yüzden "14.", "BÖLÜM 14:" ve noktasız "14 BAŞLIK" stillerine bakıyoruz,
    "14.1" gibi alt başlıklarla karıştırmıyoruz.
    """
    pattern = r"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*14\s*(?:[.:]\s+|\s+(?=[A-ZÇĞİÖŞÜ]))"
    m_start = re.search(pattern, text)
    if not m_start:
        return None
    start = m_start.start()
    end_pattern = r"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*15\s*(?:[.:]\s+|\s+(?=[A-ZÇĞİÖŞÜ]))"
    m_end = re.search(end_pattern, text[start:])
    end = start + m_end.start() if m_end else len(text)
    return text[start:end]


def _is_section_label(line: str, label: str) -> bool:
    """'ADR' gibi bir bölüm etiketini, font kodlama hatası yüzünden satır
    sonuna sıçramış tek başına Türkçe büyük harflere (İ, Ğ, Ş ...)
    toleranslı şekilde karşılaştırır."""
    cleaned = re.sub(r"[İĞŞÖÜÇİığşöüç\s]+$", "", line.strip())
    return cleaned == label


NOT_IN_SCOPE_PATTERNS = [
    # "...kapsamında değildir" / "kapsamı dışındadır" -- ÖNEMLİ (güvenlik):
    # bu ifade öncesinde "tehlikeli madde/mal", "taşımacılık/nakliye" veya
    # "ADR/RID/IMDG/IATA" gibi gerçekten ADR kapsamıyla ilgili bir kelime
    # geçmesi ZORUNLU. Aksi halde Bölüm 14.7 "Marpol ... bu kapsamda
    # değildir" gibi ADR ile hiç ilgisi olmayan, başka bir mevzuata
    # (Marpol/IBC) atıfta bulunan cümleler yanlışlıkla "ADR kapsamında
    # değil" sanılıp tehlikeli bir madde "kapsam dışı" işaretlenebilir
    # (örn. Argon/HABAŞ şablonu).
    r"(tehlikeli\s+(madde|mal)|ta[şs][ıi]mac[ıi]l[ıi][ğg]?[ıi]?|nakliye|ADR|RID|IMDG|IATA)"
    r"[^.\n]{0,60}?kapsam\w*\s+(de|dı)[ğg]?ildir",
    r"(tehlikeli\s+(madde|mal)|ta[şs][ıi]mac[ıi]l[ıi][ğg]?[ıi]?|nakliye|ADR|RID|IMDG|IATA)"
    r"[^.\n]{0,60}?kapsam\w*\s+dı[şs][ıi]ndad[ıi]r",
    r"tehlikeli\s+madde\s+(de|dı)[ğg]?ildir",
    r"tehlikeli\s+mal\s+(de|dı)[ğg]?ildir",                       # "Tehlikeli mal değildir"
    r"tehlikeli\s+madde\s+olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r",
    r"tehlikeli\s+madde\s+olarak\s+düzenlenmemi[şsĢģ]t[ıi]r",        # "Tehlikeli madde olarak düzenlenmemiştir" (Ģ: CHT font bozulması)
    r"tehlikeli\s+madde\s+s[ıi]n[ıi]f[ıi]na\s+girmez",             # "...tehlikeli madde sınıfına girmez"
    r"\bdüzenleme\s+yoktur\b",                                     # "Düzenleme yoktur"
    r"s[ıi]n[ıi]fland[ıi]rma\s+belirtilmemi[şsĢģ]tir",           # "Sınıflandırma belirtilmemiştir" (Ģ: CHT font bozulması)
    r"s[ıi]n[ıi]fland[ıi]rma\s+yap[ıi]lmam[ıi][şsĢģ]t[ıi]r",   # "Sınıflandırma Yapılmamıştır" (Everlight şablonu)
    # İngilizce MSDS'lerde görülen açık "kapsam dışı" ifadeleri
    r"not\s+(?:included|classified)\s+(?:as\s+)?(?:any\s+)?(?:dangerous\s+goods|transport\s+class)",
    r"not\s+regulated\s+(?:for|as)\s+transport",
    r"not\s+regulated\s+as\s+(?:a\s+)?dangerous",   # "Not regulated as a dangerous good/goods" veya "as dangerous goods"
    r"no(?:t)?\s+dangerous\s+goods\s+(?:for|in)\s+transport",
    r"not\s+dangerous\s+goods\b",                                  # "Not dangerous goods"
    r"not\s+a\s+dot\s+controlled\s+material",                      # ABD DOT formatı
]


def explicit_not_in_scope(section14_text: str) -> bool:
    """Bölüm 14'te 'tehlikeli maddelerin taşımacılığı ... kapsamında
    değildir (IMDG, IATA, ADR/RID)' veya İngilizce 'not included any
    transport class' türü açık bir ifade var mı kontrol eder. Bu durumda
    ürünün ADR kapsamı dışında olduğunu, sadece "ADR" satırının
    yokluğuna bakarak değil, doğrudan metinden anlarız."""
    for p in NOT_IN_SCOPE_PATTERNS:
        for m in re.finditer(p, section14_text, re.IGNORECASE):
            # ÖNEMLİ (güvenlik): eşleşmenin başladığı noktadan biraz
            # öncesine bakarak, cümlenin asıl konusunun Marpol/IBC gibi
            # ADR ile ilgisi olmayan başka bir mevzuat olup olmadığını
            # kontrol ediyoruz. Örn. "14.7 Marpol ... IBC Koduna Göre
            # Toplu Taşımacılık: Bu kapsamda değildir." cümlesinde
            # "Taşımacılık" kelimesi regex'in bağlam testini geçer, ama
            # "Marpol"/"IBC Kod" eşleşmeden ÖNCE geçtiği için asıl konu
            # ADR/RID/IMDG/IATA değildir -- bu durumda eşleşmeyi geçersiz
            # sayıyoruz (örn. Argon/HABAŞ şablonu) ve aynı desen için
            # metnin kalanında başka bir (gerçek) eşleşme olup olmadığına
            # bakmaya devam ediyoruz.
            onceki_tam = section14_text[:m.start()]
            # Aynı cümlenin başına kadar geri git (son nokta veya satır
            # sonu); önceki cümlede geçen "Marpol" kelimesi bu eşleşmeyi
            # etkilememeli.
            cumle_baslangic = max(
                onceki_tam.rfind("."), onceki_tam.rfind("\n")) + 1
            onceki = section14_text[cumle_baslangic:m.start()]
            if re.search(r"marpol|\bIBC\s*Kod", onceki, re.IGNORECASE):
                continue
            return True
    # "14.1 UN Numarası : N/A" / İngilizce "14.1. UN ... number: None" gibi
    # UN no alanının açıkça boş/uygulanamaz olarak işaretlenmesi de güçlü
    # bir "kapsam dışı" göstergesidir (dil bağımsız: NUMARASI/NO./number).
    # "14.1" öneki opsiyonel (bazı şablonlarda alt başlık numarası yok);
    # etiket ile değer arasında nokta/satır sonu da olabilir ("numarası.\nUygulanmaz.").
    m = re.search(
        r"(?:14\s*\.?\s*1\b\.?\s*)?UN[\s-]*(?:NUMARAS[ıi]|NO\.?|\([^)]*\)\s*number)"
        r"[.\s:]*"
        r"(N\s*/\s*A|YOK|UYGULAN[AM]*Z|NONE|-)\b",
        section14_text, re.IGNORECASE)
    if m:
        return True
    return False


def find_adr_block(section14_text: str):
    """Bölüm 14 içinde tam olarak 'ADR' başlığına sahip bloğu bul (ADNR ile karıştırma)."""
    lines = section14_text.split("\n")
    for i, line in enumerate(lines):
        if _is_section_label(line, "ADR"):
            block_lines = []
            for l in lines[i + 1:]:
                if l.strip() == "":
                    break
                block_lines.append(l)
            return block_lines
    return None


ROMAN_PG = re.compile(r"^(I|II|III)$")
NUM_TOKEN = re.compile(r"^\d{1,2}(\.\d)?$")


def parse_adr_first_line(line: str):
    """ADR bloğunun ilk satırından UN No / Sınıf / Paketleme Grubu çıkarır.

    NOT: Önceden çoklu-boşluk pozisyonuna göre sütun ayırıyorduk; ama farklı
    PDF kütüphaneleri (pdftotext/pdfplumber) aynı tabloyu farklı boşluk
    miktarlarıyla yeniden oluşturabiliyor. Bu yüzden artık sadece "UN ####"
    ile başlamasına bakıyor, ardından sınıf (tek/çift haneli sayı) ve
    paketleme grubu (I/II/III) için satırın tamamını tek tek kelime kelime
    tarıyoruz; bu, boşluk sayısından bağımsız çalışır.
    """
    line = line.strip()
    m = re.match(r"^UN\s+(\d{4})\b", line)
    if not m:
        return None
    un_no = m.group(1)
    rest = line[m.end():]
    sinif = None
    paketleme_grubu = None
    for t in re.findall(r"\S+", rest):
        t = t.strip(",.")
        if sinif is None and NUM_TOKEN.match(t):
            sinif = t
        if ROMAN_PG.match(t):
            paketleme_grubu = t
    return {"un_no": un_no, "sinif": sinif, "paketleme_grubu": paketleme_grubu}


def parse_numbered_subsections(sec14_text: str):
    """'14.1. UN NUMARASI\\n2790\\n2790...' (AK-KİM tarzı, değer doğrudan
    altında) veya '14.1.UN Numarası\\nUN No. (ADR/RID/ADN) 1760' (SERİN
    KİMYA tarzı, değerden önce bir etiket satırı daha var) gibi numaralı
    alt başlık + değer formatlarından UN no/sınıf/paketleme grubunu
    çıkarır -- 'ADR' diye tek başına bir satır yok, bu yüzden
    find_adr_block bu formatlarda hiçbir şey bulamıyor.
    Başlık ile değer arasında ekstra etiket satırı olabileceği için,
    başlıktan sonraki makul bir pencere (~150 karakter) içinde ilk uygun
    değer aranır (DOTALL: satır sonları da bu pencereye dahildir).
    """
    un_no = None
    m = re.search(
        r"14\s*\.?\s*1\b\.?\s*[ÜU]N[\s-]*NUMARAS[ıi].{0,150}?\b(\d{3,4})\b",
        sec14_text, re.IGNORECASE | re.DOTALL)
    if m:
        un_no = m.group(1)
    else:
        # "UN NO. KARAYOLU 3412" gibi numaralı alt başlık olmadan düz
        # "UN NO. <bir şeyler> <sayı>" etiketi (örn. SETACID VS-N şablonu).
        m = re.search(r"\b[ÜU]N\s*N[Oo]\.?.{0,30}?\b(\d{3,4})\b", sec14_text, re.DOTALL)
        if m:
            un_no = m.group(1)
        else:
            # Bazı şablonlarda Bölüm 14'ün en başında "UN 2790-ASETİK ASİT..."
            # şeklinde özet bir satır da bulunur.
            m = re.search(r"\bUN\s*[-:]?\s*(\d{3,4})\b", sec14_text)
            if m:
                un_no = m.group(1)
    if not un_no:
        return None

    sinif = None

    def _gecerli_sinif(val: str, un_no: str) -> bool:
        """ADR tehlike sınıfı olarak geçerli bir değer mi?
        ADR sınıfları 1-9 arasındadır (1, 1.4, 2.2, 3, 6.1, 8, 9 vb.).
        Tamsayı kısmı 9'u aşan her değer (10, 11, 14.3, 14.4 …) bir
        sınıf değil, başka bir sayıdır — reddedilir. UN no'nun kendisi
        de reddedilir."""
        if not val or val == str(un_no):
            return False
        try:
            tamsayi = int(str(val).split(".")[0])
        except ValueError:
            return False
        return 1 <= tamsayi <= 9

    m = re.search(
        r"14\s*\.?\s*3\b\.?\s*[^\n]{0,60}?S[ıi]N[ıi]F.{0,300}?\b(\d+(?:\.\d+)?)\b",
        sec14_text, re.IGNORECASE | re.DOTALL)
    if m and not _gecerli_sinif(m.group(1), un_no):
        m = None
    if m and m.group(1) == str(un_no):
        # İlk bulunan sayı UN no'nun kendisinin tekrarı olabilir (örn.
        # açıklayıcı metinde "ADR ÜN 2014 ... 5.1, P.G. II" gibi UN no
        # önce geçiyorsa) -- aynı pencerede bir sonraki sayıyı dene.
        rest = sec14_text[m.end():m.end() + 150]
        m_next = re.search(r"\b(\d+(?:\.\d+)?)\b", rest)
        m = m_next if (m_next and _gecerli_sinif(m_next.group(1), un_no)) else None
    # AK-KİM tarzı çapraz tablo formatı: başlık "14.3. TAŞIMACILIK
    # ZARARLILIK" şeklinde SINIF kelimesi olmadan biter; değer satırı
    # (örn. "8  8  8  8") sonraki satırda, "SINIFI" kelimesi daha
    # sonra geliyor. Bu yüzden [^\n]{0,60}?SINIF deseni eşleşmiyor.
    # Bu formatta "14.3." başlığının hemen altındaki satırdan ADR
    # sütununa karşılık gelen ilk sayıyı alıyoruz. Ana 14.3 deseni
    # başarılı olduysa (m != None) bu bloğa girmiyoruz.
    if m is None:
        m_akkim = re.search(
            r"14\s*\.?\s*3\b[^\n]*\n\s*(\d+(?:\.\d+)?)\b",
            sec14_text, re.IGNORECASE)
        if m_akkim and _gecerli_sinif(m_akkim.group(1), un_no):
            sinif = m_akkim.group(1)
        # "ADR SINIFI NOSU. 8" gibi numaralı alt başlık olmadan düz etiket.
        if sinif is None:
            m = re.search(
                r"\bADR\w*\s*S[ıi]N[ıi]F\w*.{0,30}?\b(\d+(?:\.\d+)?)\b",
                sec14_text, re.IGNORECASE | re.DOTALL)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # "ADR ÜN 1832 8.II" gibi UN no'nun hemen ardından gelen
            # "Sınıf.PaketlemeGrubu" birleşik kısaltması (tek satırlık
            # özet format).
            m = re.search(rf"\bUN\s*{re.escape(str(un_no))}\s+(\d+(?:\.\d+)?)\.(I{{1,3}})\b", sec14_text)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # "ADR ÜN 2014 ... 5.1, P.G. II" tarzı satır içi birleşik
            # format: mod adı + ÜN/UN + no + uzun isim (parantez içinde
            # virgül olabilir) + virgül + sınıf + virgül + P.G.
            # [^,\n]* parantez içindeki virgüle takılır; bu yüzden
            # ADR/ÜN/UN içeren satırı izole edip P.G. öncesi sınıfı arıyoruz.
            m = re.search(
                rf"(?m)^[^\n]*\bADR\b[^\n]*[ÜU]N\s+{re.escape(str(un_no))}[^\n]*",
                sec14_text, re.IGNORECASE)
            if m:
                satir = m.group(0)
                m_pg = re.search(r",\s*(\d+(?:\.\d+)?)\s*,\s*P[\.\s]*G\.", satir, re.IGNORECASE)
                if m_pg and _gecerli_sinif(m_pg.group(1), un_no):
                    sinif = m_pg.group(1)
        if sinif is None:
            # HABAŞ tarzı şablon: "14.1. ADR:" alt-bloğu içinde "ADR"
            # kelimesi olmadan, satır başında numarasız düz "Sınıfı :"
            # etiketi (örn. "Sınıfı : 2"). İKİ NOKTA (:) ZORUNLU
            # tutuyoruz -- AK-KİM tarzı tablolarda başlık satırından
            # taşan "SINIFI" kelimesi satır başında tek başına görünür
            # (iki nokta yoktur); iki nokta şartı bu yanlış eşleşmeyi
            # engeller. _gecerli_sinif() ek güvence sağlar.
            m = re.search(
                r"(?im)^\s*S[ıi]n[ıi]f[ıi]?\s*:\s*(\d+(?:\.\d+)?)\b",
                sec14_text)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
    else:
        sinif = m.group(1)

    pg = None
    m = re.search(
        r"14\s*\.?\s*4\b\.?\s*[^\n]{0,60}?GRUBU.{0,400}?\b(I{1,3})\b",
        sec14_text, re.IGNORECASE | re.DOTALL)
    if m:
        pg = m.group(1)
    else:
        # "ADR/RID ambalajlama grubu II" / "IMDG PAKET GR. III" gibi numaralı alt
        # başlık olmadan düz etiket (örn. SETACID VS-N şablonu).
        # ADR[\w/]* → ADR/RID gibi eğik çizgili ifadeleri de kapsar.
        m = re.search(
            r"\bADR[\w/]*\s*(?:PAKET|AMBALAJ\w*)\s*GR\w*\.?.{0,20}?\b(I{1,3})\b",
            sec14_text, re.IGNORECASE | re.DOTALL)
        if m:
            pg = m.group(1)
        else:
            # "UN 1832 8.II" gibi UN no'nun hemen ardından gelen
            # "Sınıf.PaketlemeGrubu" birleşik kısaltması.
            m = re.search(rf"\bUN\s*{re.escape(str(un_no))}\s+\d+(?:\.\d+)?\.(I{{1,3}})\b", sec14_text)
            if m:
                pg = m.group(1)

    return {"un_no": un_no, "sinif": sinif, "paketleme_grubu": pg}


def extract_adr_info(pdf_path: str):
    """Tek bir PDF'ten ADR (Bölüm 14) bilgisini VE Versiyon 2'nin diğer
    sütunları (tedarikçi, fonksiyon, cas no, H kodları vb.) için Bölüm
    1/2/3'ten ek bilgiyi tek seferde çıkarır."""
    text = pdf_to_text(pdf_path)
    result = {
        "revize_tarihi": extract_revize_tarihi(text),
        "onerilen_ad": extract_suggested_name(text),
        "un_no": None,
        "sinif": None,
        "paketleme_grubu": None,
        "adr_kapsaminda": None,  # True / False / None (belirsiz->manuel kontrol)
        "ham_metin_bulundu": False,
    }
    result.update(extract_full_info(pdf_path, text=text))

    sec14 = find_section14_text(text)
    if sec14 is None:
        # Bölüm 14 bile bulunamadıysa -> manuel kontrol gerekli
        return result

    result["ham_metin_bulundu"] = True

    # Yöntem 1: Tek başına "ADR" satırı + altındaki "UN ####" deseni
    # (örn. Ashland/DyStar şablonu).
    block = find_adr_block(sec14)
    if block:
        first_line = next((l for l in block if l.strip()), None)
        if first_line:
            parsed = parse_adr_first_line(first_line)
            if parsed:
                result["adr_kapsaminda"] = True
                result["un_no"] = parsed["un_no"]
                result["sinif"] = parsed["sinif"]
                result["paketleme_grubu"] = parsed["paketleme_grubu"]
                return result

    # Yöntem 2: "14.1. UN NUMARASI" / "14.3. ... SINIFI" / "14.4. AMBALAJLAMA
    # GRUBU" gibi numaralı alt başlık + değer deseni (örn. AK-KİM şablonu).
    parsed2 = parse_numbered_subsections(sec14)
    if parsed2:
        result["adr_kapsaminda"] = True
        result["un_no"] = parsed2["un_no"]
        result["sinif"] = parsed2["sinif"]
        result["paketleme_grubu"] = parsed2["paketleme_grubu"]
        return result

    # ÖNEMLİ (güvenlik sırası): Gerçek bir UN no bulunamadıysa, ŞİMDİ açık
    # "kapsam dışı" ifadesine bakıyoruz. Bu kontrolü UN aramadan ÖNCE değil
    # SONRA yapıyoruz -- aksi halde, metnin başka bir yerinde geçen "X için
    # düzenleme yoktur" gibi bir ifade, başka bir yerde gerçekten var olan
    # bir UN numarasını yanlışlıkla ezip "kapsam dışı" gösterebilirdi.
    # Gerçek veri bulunduğunda HER ZAMAN ona güvenilir.
    if explicit_not_in_scope(sec14):
        result["adr_kapsaminda"] = False
        return result

    # ÖNEMLİ (güvenlik): Hiçbir yöntem UN no bulamadıysa VE açık bir
    # "kapsam dışı" ifadesi de yoksa, bunu KESİN "ADR kapsamında değil"
    # SAYMIYORUZ -- format tanınamamış olabilir. Yanlışlıkla tehlikeli bir
    # maddeyi "kapsam dışı" göstermemek için belirsiz/manuel kontrol
    # gerekli (adr_kapsaminda=None) olarak bırakıyoruz.
    return result


if __name__ == "__main__":
    import sys
    for path in sys.argv[1:]:
        print("=" * 80)
        print(path)
        print(extract_adr_info(path))
