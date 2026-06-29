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
    except Exception as e1:
        try:
            import fitz
            text_parts = []
            with fitz.open(pdf_path) as doc:
                for page in doc:
                    text_parts.append(page.get_text())
            return "\n".join(text_parts)
        except Exception as e2:
            # Her iki kutuphane de basarisiz oldu; hatayi RuntimeError olarak
            # yukari tasiyoruz ki extract_adr_info() uzerinden app.py
            # kullaniciya anlamli bir hata mesaji gosterebilsin.
            raise RuntimeError(
                f"PDF okunamadi. pdfplumber: {str(e1)[:120]} | PyMuPDF: {str(e2)[:120]}"
            ) from e2
        
def normalize_pdf_text(text: str) -> str:
    """
    PDF extraction sonrası oluşan OCR/PDF bozulmalarını düzeltir.
    Türkçe SDS/MSDS belgeleri için optimize edilmiştir.
    """

    if not text:
        return ""

    # non-breaking space temizliği
    text = text.replace("\xa0", " ")

    # fazla boşlukları temizle
    text = re.sub(r"[ \t]+", " ", text)

    # satır sonlarını normalize et
    text = re.sub(r"\r\n?", "\n", text)

    # UN 1 2 0 3 -> UN1203
    text = re.sub(
        r"U\s*N\s*([0-9])\s*([0-9])\s*([0-9])\s*([0-9])",
        r"UN\1\2\3\4",
        text,
        flags=re.IGNORECASE
    )

    # P G II -> PG II  (IGNORECASE: taranmış PDF'lerde "p g ii" de gelir)
    text = re.sub(
        r"P\s*G\s*(I{1,3})",
        r"PG \1",
        text,
        flags=re.IGNORECASE
    )

    # Class : 8 -> Class 8
    text = re.sub(
        r"Class\s*[:\-]\s*",
        "Class ",
        text,
        flags=re.IGNORECASE
    )

    # ADR / RID -> ADR/RID
    text = re.sub(
        r"ADR\s*/\s*RID",
        "ADR/RID",
        text,
        flags=re.IGNORECASE
    )

    # Windows-1252 / Latin-1 encoding bozuklukları:
    # pdfplumber bazı PDF'lerde Türkçe karakterleri yanlış çözüyor.
    # En sık görülenler:
    #   Ģ  (U+0122) -> ş   (S cedilla -> s cedilla)
    #   ġ  (U+0121) -> ğ   (g dot above -> g breve)
    #   ı  (U+0131) zaten doğru gelir; İ bazen Ġ (U+0120) olarak gelir
    text = text.replace("\u0122", "ş").replace("\u0122".upper(), "Ş")
    text = text.replace("\u0121", "ğ").replace("\u0120", "Ğ")
    # Doğrudan karakter olarak da ekle (kaynak dosya encoding'ine bağlı)
    text = text.replace("Ģ", "ş").replace("ģ", "ş")
    text = text.replace("ġ", "ğ").replace("Ġ", "Ğ")

    return text

def extract_revize_tarihi(text: str):
    # Farklı üreticiler farklı etiketler kullanıyor:
    #  - "Revize Edildiği Tarih: ..."   (örn. Ashland şablonu)
    #  - "Revizyon tarihi: ..."         (örn. DyStar/Sera şablonu)
    #  - "Yeni düzenleme tarihi ..."    (örn. Eksoy/GBF şablonu)
    #  - "Yayın Tarihi :..."            (örn. Pentakim şablonu)
    # PDF font kodlaması bazen "ğ" gibi karakterleri boşluğa çeviriyor
    # ("Edildiği" -> "Edildi i"); bu yüzden ortadaki kısma sıkı bağlı değiliz.
    # "Reviz\w*" -> "Revize", "Revizyon", "Revizyonu" gibi tüm türevleri yakalar.
    patterns = [
        r"Reviz\w*\b.{0,15}[Tt]arih\w*\s*:?\s*([\d./]+)",
        r"Yeni\s+düzen\w*\s+tarihi\s*:?\s*([\d./]+)",
        r"Yay[ıi]n\s*[Tt]arihi\s*:?\s*([\d./]+)",
        r"\bRevision\s*:?\s*([\d./]+)",  # İngilizce MSDS
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
    m = re.search(r"Tedarikçi\s*\n?\s*([^\n]{3,90})", bolum1)
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
    tüm harfler değişmeden (zorunlu) kalır."""
    degisenler = {"ı": "ı?", "İ": "İ?", "ş": "ş?", "Ş": "Ş?", "ğ": "ğ?", "Ğ": "Ğ?"}
    return "".join(degisenler.get(ch, re.escape(ch)) for ch in kelime)


def extract_fonksiyon(text: str):
    """Bölüm 1.2'den ürünün kullanım amacını/fonksiyonunu çıkarır."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    patterns = [
        r"(?m)^\s*" + _esnek_desen("Belirlenmiş kullanımlar") + r"\b\s*:?\s*\n?\s*([^\n]{3,80})",
        r"(?m)^\s*" + _esnek_desen("Kullanım alanı") + r"\b\s*:\s*([^\n]{3,80})",
        r"(?m)^\s*Kullanim\s*:\s*\n?\s*([^\n]{3,80})",
        r"(?m)^\s*Relevant\s+identified\s+uses\s*:?\s*([^\n]{3,80})",  # İngilizce MSDS
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
        text = normalize_pdf_text(pdf_to_text(pdf_path))
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
    r"kapsam\w*\s+(de|dı)[ğg]?ildir",          # "...kapsamında değildir" / "kapsamı dışındadır" / ASCII "degildir" varyasyonları
    r"kapsam\w*\s+dı[şs][ıi]ndad[ıi]r",
    r"tehlikeli\s+madde\s+(de|dı)[ğg]?ildir",
    r"tehlikeli\s+mal\s+(de|dı)[ğg]?ildir",                       # "Tehlikeli mal değildir"
    r"tehlikeli\s+madde\s+olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r",
    r"tehlikeli\s+madde\s+olarak\s+düzenlenmemi[şs]t[ıi]r",        # "Tehlikeli madde olarak düzenlenmemiştir"
    r"tehlikeli\s+madde\s+s[ıi]n[ıi]f[ıi]na\s+girmez",             # "...tehlikeli madde sınıfına girmez"
    r"\bdüzenleme\s+yoktur\b",                                     # "Düzenleme yoktur"
    # İngilizce MSDS'lerde görülen açık "kapsam dışı" ifadeleri
    r"not\s+(?:included|classified)\s+(?:as\s+)?(?:any\s+)?(?:dangerous\s+goods|transport\s+class)",
    r"not\s+regulated\s+(?:for|as)\s+transport",
    r"no(?:t)?\s+dangerous\s+goods\s+(?:for|in)\s+transport",
    r"not\s+dangerous\s+goods\b",                                  # "Not dangerous goods"
    r"not\s+a\s+dot\s+controlled\s+material", 
    r"karayolu taşımacılığında düzenlemeye tabi değildir",
    r"adr kapsamında değildir",
    r"tehlikeli madde olarak sınıflandırılmamıştır",
    r"taşımacılık açısından tehlikeli değildir",# ABD DOT formatı
]


def explicit_not_in_scope(section14_text: str) -> bool:
    """Bölüm 14'te 'tehlikeli maddelerin taşımacılığı ... kapsamında
    değildir (IMDG, IATA, ADR/RID)' veya İngilizce 'not included any
    transport class' türü açık bir ifade var mı kontrol eder. Bu durumda
    ürünün ADR kapsamı dışında olduğunu, sadece "ADR" satırının
    yokluğuna bakarak değil, doğrudan metinden anlarız."""
        # ---------------------------------------------------------
    # Eğer ADR kısmında gerçek bir UN numarası varsa
    # doğrudan kapsam dışı sayma
    # ---------------------------------------------------------

    adr_positive = re.search(
        r"""
        ADR
        .{0,250}?
        \bUN[-\s:]?\d{3,4}\b
        """,
        section14_text,
        re.IGNORECASE | re.DOTALL | re.VERBOSE
    )

    if adr_positive:
        return False
    for p in NOT_IN_SCOPE_PATTERNS:
        if re.search(p, section14_text, re.IGNORECASE):
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
    """
    Bölüm 14 içinde ADR bloğunu bul.
    Türkçe SDS formatlarına toleranslıdır.
    """

    lines = section14_text.split("\n")

    for i, line in enumerate(lines):

        clean = line.strip().upper()

        if (
            clean == "ADR"
            or "ADR/RID" in clean
            or clean.startswith("ADR ")
            or "KARAYOLU" in clean
            or "ROAD" in clean
        ):

            block_lines = []

            for l in lines[i + 1:]:

                # boş satır görünce blok bitsin
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
    """
    Bölüm 14 içindeki numaralı alt başlıklardan
    UN / Sınıf / Paketleme Grubu çıkarır.

    Türkçe SDS/MSDS formatlarına toleranslıdır.
    """

    # ---------------------------------------------------------
    # UN NUMARASI
    # ---------------------------------------------------------

    un_no = None

    m = re.search(
        r"14\s*\.?\s*1\b\.?\s*UN[\s-]*NUMARAS[ıi].{0,150}?\b(\d{3,4})\b",
        sec14_text,
        re.IGNORECASE | re.DOTALL
    )

    if m:
        un_no = m.group(1)

    else:
        # UN NO. KARAYOLU 3412
        m = re.search(
            r"\bUN\s*N[Oo]\.?.{0,30}?\b(\d{3,4})\b",
            sec14_text,
            re.IGNORECASE | re.DOTALL
        )

        if m:
            un_no = m.group(1)

        else:
            # UN1760 / UN 1760 / UN-1760
            m = re.search(
                r"""
                \b
                U\s*N
                (?:[-\s]*NO\.?)?
                (?:[-\s]*NUMARASI)?
                \s*[:\-]?\s*
                (\d{3,4})
                \b
                """,
                sec14_text,
                re.IGNORECASE | re.VERBOSE
            )

            if m:
                un_no = m.group(1)

    # UN numaraları 1000-3599 aralığındadır (ADR Tablo A'ya göre).
    # Bu aralık dışındaki sayılar (yıl, sayfa no, belge no vb.) UN no olamaz.
    if un_no and not (1000 <= int(un_no) <= 3599):
        un_no = None

    if not un_no:
        return None

    # ---------------------------------------------------------
    # SADECE ADR CONTEXT İÇİNDE ÇALIŞ
    # ---------------------------------------------------------

    adr_window_match = re.search(
        r"(ADR.*?)(IMDG|IATA|DENİZYOLU|HAVAYOLU|$)",
        sec14_text,
        re.IGNORECASE | re.DOTALL
    )

    adr_window = (
        adr_window_match.group(1)
        if adr_window_match
        else sec14_text
    )

    # ---------------------------------------------------------
    # SINIF
    # ---------------------------------------------------------

    sinif = None

    # 14.3 başlığı + SINIF kelimesi + sayı (adr_window ve sec14_text'e bak)
    for _search_text in (adr_window, sec14_text):
        m = re.search(
            r"14\s*\.?\s*3\b\.?\s*[^\n]{0,60}?S[ıi]N[ıi]F.{0,150}?\b(\d+(?:\.\d+)?)\b",
            _search_text,
            re.IGNORECASE | re.DOTALL
        )
        if m and m.group(1) != str(un_no):
            sinif = m.group(1)
            break
        if m and m.group(1) == str(un_no):
            # yanlışlıkla UN numarasını yakaladıysa
            rest = _search_text[m.end():m.end() + 150]
            m_next = re.search(r"\b(\d+(?:\.\d+)?)\b", rest)
            if m_next and m_next.group(1) != str(un_no):
                sinif = m_next.group(1)
                break

    # "Taşıma sınıfı(ları) 9" formatı için ek fallback
    if sinif is None:
        m = re.search(
            r"14\s*\.?\s*3\b[^\n]{0,80}?\b(\d+(?:\.\d+)?)\s*$",
            sec14_text,
            re.IGNORECASE | re.MULTILINE
        )
        if m and m.group(1) != str(un_no):
            sinif = m.group(1)

    # Türkçe fallback: "SINIFI / TEHLİKE SINIFI / ADR SINIFI / Taşıma sınıfı"
    if sinif is None:
        m = re.search(
            r"(?:Ta[şs][ıi]ma\s+)?S[ıi]N[ıi]F[ıi]?(?:\([^)]*\))?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
            sec14_text,
            re.IGNORECASE
        )
        if m and m.group(1) != str(un_no):
            sinif = m.group(1)

    # ADR SINIFI NOSU 8
    if sinif is None:

        m = re.search(
            r"\bADR\w*\s*S[ıi]N[ıi]F\w*.{0,30}?\b(\d+(?:\.\d+)?)\b",
            adr_window,
            re.IGNORECASE | re.DOTALL
        )

        if m and m.group(1) != str(un_no):
            sinif = m.group(1)

    # UN 1832 8.II
    if sinif is None:

        m = re.search(
            rf"\bUN\s*{re.escape(str(un_no))}\s+(\d+(?:\.\d+)?)\.(I{{1,3}})\b",
            adr_window,
            re.IGNORECASE
        )

        if m:
            sinif = m.group(1)

    # ---------------------------------------------------------
    # PAKETLEME GRUBU
    # ---------------------------------------------------------

    pg = None

    # 14.4 başlığını hem adr_window hem sec14_text'te ara
    for _pg_text in (adr_window, sec14_text):
        m_pg = re.search(
            r"14\s*\.?\s*4\b[^\n]{0,80}?\b(I{1,3})\b",
            _pg_text,
            re.IGNORECASE
        )
        if m_pg:
            pg = m_pg.group(1)
            break

    if pg is None:
        m_pg = re.search(
            r"14\s*\.?\s*4\b[^\n]{0,80}?\b(I{1,3})\s*$",
            sec14_text,
            re.IGNORECASE | re.MULTILINE
        )
        if m_pg:
            pg = m_pg.group(1)

    m = re.search(
        r"14\s*\.?\s*4\b\.?\s*[^\n]{0,60}?GRUBU.{0,150}?\b(I{1,3})\b",
        adr_window,
        re.IGNORECASE | re.DOTALL
    )

    if m:
        pg = m.group(1)

    # Türkçe fallback
    if pg is None:

        m = re.search(
            r"(?:PAKETLEME GRUBU|AMBALAJLAMA GRUBU|PG)"
            r".{0,40}?\b(I{1,3})\b",
            adr_window,
            re.IGNORECASE | re.DOTALL
        )

        if m:
            pg = m.group(1)

    # ADR PAKET GRUBU III
    if pg is None:

        m = re.search(
            r"\bADR\w*\s*(?:PAKET|AMBALAJ\w*)\s*GR\w*\.?.{0,20}?\b(I{1,3})\b",
            adr_window,
            re.IGNORECASE | re.DOTALL
        )

        if m:
            pg = m.group(1)

    # UN 1832 8.II
    if pg is None:

        m = re.search(
            rf"\bUN\s*{re.escape(str(un_no))}\s+\d+(?:\.\d+)?\.(I{{1,3}})\b",
            adr_window,
            re.IGNORECASE
        )

        if m:
            pg = m.group(1)

    # ---------------------------------------------------------
    # SINIFLANDIRMA KODU
    # ---------------------------------------------------------

    siniflandirma_kodu = None

    m = re.search(
        r"""
        (?:SINIFLANDIRMA\s*KODU|CLASSIFICATION\s*CODE)
        [^\n:]{0,40}
        [:]?\s*
        ([A-Z0-9]+)
        """,
        adr_window,
        re.IGNORECASE | re.VERBOSE
    )

    if m:
        siniflandirma_kodu = m.group(1).strip().upper()

    # ---------------------------------------------------------
    # SINIF 2: Etiket bilgisinden siniflandirma kodu türet
    # "Etiket Bilgisi : 2.2" veya "Etiket : 2.1" gibi alanlar
    # doğrudan sınıflandırma kodu yazmaz. ADR kuralına göre:
    #   2.1 → F  (parlayıcı gaz)
    #   2.2 → A  (basınçlı/boğucu gaz, alevlenmez)
    #   2.3 → T, TF, TC, TO, TFC, TOC vb. (zehirli gaz)
    # PDF'te SINIFLANDIRMA KODU alanı yoksa etiket değerinden türetiriz.
    # ---------------------------------------------------------
    if siniflandirma_kodu is None and sinif and str(sinif).strip() == "2":
        etiket_m = re.search(
            r"(?:Etiket(?:\s+Bilgisi)?|Label)\s*[:\-]?\s*(2\.\d)",
            adr_window,
            re.IGNORECASE
        )
        if etiket_m:
            etiket_deger = etiket_m.group(1).strip()
            _etiket_map = {
                "2.1": "F",
                "2.2": "A",
                "2.3": "T",
            }
            siniflandirma_kodu = _etiket_map.get(etiket_deger)

    return {
        "un_no": un_no,
        "sinif": sinif,
        "paketleme_grubu": pg,
        "siniflandirma_kodu": siniflandirma_kodu,
    }
    
    
def parse_adr_table(sec14_text):
    """
    Tablo biçimindeki ADR/RID kayıtlarını okumaya çalışır.
    """

    # ADR/RID satırı
    m = re.search(
        r"""
        ADR\s*/?\s*RID
        .*?
        UN\s*[-:]?\s*(\d{3,4})
        .*?
        \b(\d(?:\.\d)?)\b
        .*?
        \b(I{1,3})\b
        """,
        sec14_text,
        re.IGNORECASE | re.DOTALL | re.VERBOSE
    )

    if not m:
        return None

    return {
        "un_no": m.group(1),
        "sinif": m.group(2),
        "paketleme_grubu": m.group(3),
        "siniflandirma_kodu": None,
    }    

def extract_adr_info(pdf_path: str):
    """Tek bir PDF'ten ADR (Bölüm 14) bilgisini VE Versiyon 2'nin diğer
    sütunları (tedarikçi, fonksiyon, cas no, H kodları vb.) için Bölüm
    1/2/3'ten ek bilgiyi tek seferde çıkarır."""
    text = normalize_pdf_text(pdf_to_text(pdf_path))
    result = {
        "revize_tarihi": extract_revize_tarihi(text),
        "onerilen_ad": extract_suggested_name(text),
        "un_no": None,
        "sinif": None,
        "paketleme_grubu": None,
        "siniflandirma_kodu": None,
        "adr_kapsaminda": None,  # True / False / None (belirsiz->manuel kontrol)
        "ham_metin_bulundu": False,
    }
    result.update(extract_full_info(pdf_path, text=text))

    sec14 = find_section14_text(text)
    if sec14 is None:
        # Bölüm 14 bile bulunamadıysa -> manuel kontrol gerekli
        return result

    result["ham_metin_bulundu"] = True

    # Kapsam dışı kontrolü: "tehlikeli madde olarak düzenlenmemiştir" gibi
    # açık bir ifade varsa hiçbir UN arama yöntemini denemeden çık.
    # NOT: Bu kontrol ÖNCE yapılır; aksi halde alt başlık numaraları (14.4 vb.)
    # veya belge tarihleri (2014) yanlışlıkla UN no olarak yakalanabilir.
    if explicit_not_in_scope(sec14):
        result["adr_kapsaminda"] = False
        return result

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
    # NOT: parse_numbered_subsections daha özgül (14.x numaralı başlıklar
    # arar) olduğu için parse_adr_table'dan ÖNCE deneniyor. parse_adr_table
    # DOTALL ile çok geniş eşleşir; bu yüzden en sona bırakılıyor.
    parsed2 = parse_numbered_subsections(sec14)
    if parsed2:
        result["adr_kapsaminda"] = True
        result["un_no"] = parsed2["un_no"]
        result["sinif"] = parsed2["sinif"]
        result["paketleme_grubu"] = parsed2["paketleme_grubu"]
        result["siniflandirma_kodu"] = parsed2["siniflandirma_kodu"]
        return result

    # ---------------------------------------------------
    # Yöntem 3 : Tablo biçimindeki ADR kayıtları (son fallback)
    # DOTALL ile geniş eşleşme yaptığı için en sona bırakılır.
    # ---------------------------------------------------
    parsed3 = parse_adr_table(sec14)
    if parsed3:
        result["adr_kapsaminda"] = True
        result["un_no"] = parsed3["un_no"]
        result["sinif"] = parsed3["sinif"]
        result["paketleme_grubu"] = parsed3["paketleme_grubu"]
        result["siniflandirma_kodu"] = parsed3["siniflandirma_kodu"]
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
