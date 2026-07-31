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


_YAYGIN_KELIMELER = re.compile(
    r"\b(ve|veya|için|ile|bilgi|g[üu]venlik|tarih|madde|ürün|sayfa)\b",
    re.IGNORECASE)


def _metin_bozuk_mu(text: str) -> bool:
    """Bir sayfadan çıkarılan metnin kullanılamaz olup olmadığını tespit eder.

    Bazı MSDS'ler (örn. Huntsman şablonlarının bir kısmı) metni Type3 font ile
    gömüyor. Type3 fontlarda karakterler standart bir kodlama yerine özel
    çizim prosedürleriyle tanımlanır ve genelde 'ToUnicode CMap' (glyph ID -> 
    gerçek karakter eşleşmesi) içermez. Bu durumda:
      - pdfplumber "(cid:16)(cid:17)..." gibi anlamsız glyph ID'leri döndürür,
      - PyMuPDF (fitz) ise metni YANLIŞ bir kodlamayla (örn. WinAnsi)
        yeniden yorumlar; sonuç harf İÇEREN ama tamamen anlamsız bir metin
        olur (örn. "GÜVENLİK BİLGİ FORMU" -> "?@ABCD@?E FGHH@I CJKL" gibi
        bir yer-değiştirme şifresi). Bu yüzden salt harf ORANINA bakmak
        yetersizdir -- "ABCDEFBAG" gibi bir dizi de harf oranı testini
        geçer. Onun yerine, metnin GERÇEK, çok sık geçen Türkçe kelimeler
        (ve, için, ile, bilgi, güvenlik...) içerip içermediğine bakılır;
        bu kelimelerden hiçbiri yoksa metin muhtemelen bozuk kodlanmıştır."""
    if not text or not text.strip():
        return True
    if "(cid:" in text:
        return True
    harfler = [c for c in text if c.isalpha()]
    if len(harfler) < max(10, len(text) * 0.05):
        return True
    # Yeterince uzun bir metinde (>= 80 karakter) hiç yaygın Türkçe kelime
    # geçmiyorsa, kodlama muhtemelen bozuktur.
    if len(text.strip()) >= 80 and not _YAYGIN_KELIMELER.search(text):
        return True
    return False


def _ocr_sayfa(page) -> str:
    """Tek bir PyMuPDF sayfasını yüksek çözünürlükte görüntüye çevirip
    Tesseract OCR (Türkçe dil paketi) ile okur. Type3 font gibi normal
    metin çıkarmanın tamamen başarısız olduğu durumlar için son çare
    fallback'tir -- yavaştır, bu yüzden sadece gerçekten gerektiğinde
    (bkz. _metin_bozuk_mu) çağrılır."""
    try:
        import pytesseract
        from PIL import Image
        import io
        pix = page.get_pixmap(dpi=150)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img, lang="tur")
    except Exception:
        return ""


def pdf_to_text(pdf_path: str) -> str:
    """PDF'in tüm metnini, tablo sütun hizalamasını koruyarak çıkarır.

    NOT: Önceden harici 'pdftotext' (poppler) komut satırı aracını
    kullanıyorduk; bu sadece Linux/Mac'te kurulu geliyordu ve Windows'ta
    "[WinError 2] Sistem belirtilen dosyayı bulamıyor" hatasına yol
    açıyordu. pdfplumber pip ile kurulduğu için tüm işletim sistemlerinde
    ek bir program kurmaya gerek kalmadan çalışır.

    Bazı PDF'ler bozuk/standart olmayan bir yapıya sahip olabilir (örn.
    hatalı xref tablosu) ve pdfplumber bunları açarken hata fırlatabilir.
    Bu durumda PyMuPDF (fitz) ile yedek bir deneme yapılır.

    ÜÇÜNCÜ KADEME (OCR): Bazı MSDS'ler metni Type3 font ile gömüyor (örn.
    Huntsman/NOVACRON şablonu). Type3 fontlarda genelde ToUnicode CMap
    olmadığından hem pdfplumber hem PyMuPDF metni ÇÖZEMEZ -- ikisi de
    dolu ama anlamsız/kullanılamaz metin döndürür (bkz. _metin_bozuk_mu).
    Bu durumda sayfa görüntüye çevrilip Tesseract OCR ile okunur. OCR
    yavaş olduğu için SADECE normal yöntemler başarısız olduğunda,
    sayfa bazında devreye girer. OCR de kurulu değilse (Tesseract/Türkçe
    dil paketi eksikse) program ÇÖKMEZ, sadece o sayfa için boş metin
    döner (ilgili ürün otomatik olarak "manuel kontrol gerekli" olur)."""
    sayfa_metinleri = []
    fitz_doc = None
    try:
        import fitz
        fitz_doc = fitz.open(pdf_path)
    except Exception:
        fitz_doc = None

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                metin = page.extract_text(layout=True) or ""
                if _metin_bozuk_mu(metin) and fitz_doc is not None and i < len(fitz_doc):
                    # Yöntem 2: PyMuPDF ile aynı sayfayı dene
                    fitz_metin = fitz_doc[i].get_text()
                    if not _metin_bozuk_mu(fitz_metin):
                        metin = fitz_metin
                    else:
                        # Yöntem 3: OCR (son çare, sadece bu sayfa için)
                        ocr_metin = _ocr_sayfa(fitz_doc[i])
                        if ocr_metin.strip():
                            metin = ocr_metin
                sayfa_metinleri.append(metin)
        if fitz_doc is not None:
            fitz_doc.close()
        return "\n".join(sayfa_metinleri)
    except Exception:
        # pdfplumber PDF'i hiç açamadı (örn. bozuk xref) -- tüm dokümanı
        # PyMuPDF ile, gerekirse OCR ile dene.
        try:
            if fitz_doc is None:
                import fitz
                fitz_doc = fitz.open(pdf_path)
            text_parts = []
            for page in fitz_doc:
                metin = page.get_text()
                if _metin_bozuk_mu(metin):
                    ocr_metin = _ocr_sayfa(page)
                    if ocr_metin.strip():
                        metin = ocr_metin
                text_parts.append(metin)
            fitz_doc.close()
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
        r"\bRev\.\s*[Tt]arihi\s*[\s|]*:?[\s|]*" + tarih_degeri,  # "Rev. Tarihi : 23.11.2012" kısaltması
        r"Yeni\s+düzen\w*\s+tarihi\s*:?\s*" + tarih_degeri,
        r"Yay[ıi]n\s*[Tt]arihi\s*[\s|]*:?[\s|]*" + tarih_degeri,
        r"Yay[ıi]nlanma\s*[Tt]arihi\s*:?\s*" + tarih_degeri,  # "Yayınlanma Tarihi:08.03.2019" (FOURKIM şablonu)
        r"G[öo]zden\s+geçirme\s+[Tt]arihi\s*:?\s*" + tarih_degeri,  # "Gözden geçirme tarihi: 27.11.2020" (Mavagen)
        r"\bRevision\s*:?\s*" + tarih_degeri,  # İngilizce MSDS
        r"\bRevision\s+Date\s*:?\s*" + tarih_degeri,  # "Revision Date: 12.12.2020" sütun formatı
        r"Reviewed\s+on\s*:?\s*" + tarih_degeri,  # "Reviewed on: 05.04.2017" İngilizce şablon
        r"Rev\d*\.?\s*\(\s*" + tarih_degeri + r"\s*\)",  # "Rev.1 (26.05.2016)" / "Rev1. (26.05.2016)" (Lefasol/SDS kod şablonu)
        # BASF formatı: "Tarih / gözden geçirilme tarihi: 31.01.2018"
        r"[Tt]arih\s*/\s*gözden\s+geçirilme\s+tarihi\s*:\s*" + tarih_degeri,
        # Setaş/Setas formatı: "Güncelleme tarihi: 23.03.2023"
        r"G[üu]ncelleme\s+[Tt]arihi\s*:?\s*" + tarih_degeri,
        # BİRPA/Birlik Kimya formatı: "Düzenleme Tarihi 18.07.2016" (kolon
        # yok, "Yeni" öneki de yok -- ayrı bir desen gerekiyor çünkü
        # "Yeni\s+düzen\w*\s+tarihi" bunu yakalamıyor).
        r"\bD[üu]zenleme\s+[Tt]arihi\s*:?\s*" + tarih_degeri,
        # "Düzenlenme Tarihi / Revizyon No:01.02.2022/03" -- Dyteks/ANTIQ
        # şablonu, revizyon tarihi ve numarası TEK alanda "tarih/no" olarak
        # birleşik yazılıyor; tarih kısmını al.
        r"D[üu]zenlenme\s+[Tt]arihi\s*/\s*Revizyon\s+No\s*:?\s*" + tarih_degeri,
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # Son çare: "Hazırlanma Tarihi : 19.04.2018" -- gerçek bir revizyon/
    # yayın tarihi hiçbir yerde bulunamadıysa, belgenin hazırlanma
    # tarihi de MSDS'in "yaşını" göstermek için makul bir yedektir.
    m = re.search(r"Haz[ıi]rlan?ma\s+[Tt]arihi\s*:?\s*" + tarih_degeri, text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"\bHaz\.\s*[Tt]arihi\s*[\s|]*:?[\s|]*" + tarih_degeri, text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def _urun_adi_kirp(name: str) -> str:
    """Bazı dönüştürme araçlarında ayrı alanlar (Ürün ismi, REACH No,
    CAS No, 1.2 Kullanımlar...) aralarında satır sonu olmadan tek
    "satıra" birleşiyor; ".+" ile yakalanan değer o durumda ürün
    adından çok daha fazlasını (sonraki tüm etiket/değerleri) içeriyor.
    Bilinen bir sonraki-alan işaretçisi bulunursa oradan kırp, ayrıca
    makul bir üst uzunluk sınırı uygula."""
    isaretciler = [
        r"\bREACH\s*No", r"\bCAS[\s-]*No", r"\bCAS[\s-]*[:#]", r"\b1\.2\b",
        r"\b1\.3\b", r"Tanımlanmış\s+kullan", r"Kullanım\s+alan",
        r"\bBÖLÜM\s+2\b", r"Tavsiye\s+edilen", r"Tavsiye\s+edilmeyen",
        r"Tan[ıi]m[ıi]n\s+başka", r"\bEşanlamlı",
        r"\bChemical\s+Structure\b", r"\bCAS\s*#",
    ]
    en_erken = len(name)
    for isaretci in isaretciler:
        m = re.search(isaretci, name, re.IGNORECASE)
        if m and m.start() < en_erken:
            en_erken = m.start()
    name = name[:en_erken].strip(" -:")
    return name[:80].strip()


def extract_suggested_name(text: str):
    # Çeşitli MSDS formatlarında "Ürün ismi" / "Ürün adı" / "Ticari ismi" /
    # "Ticari isim" / "Ticari adı" / "Ticari Adı" etiketleri kullanılabiliyor.
    # KRİTİK: Türkçede "isim" kelimesi ek aldığında ünsüz düşmesine uğrar
    # ("isim" + "i" -> "ismi", "isim" + "ini" -> "ismini") -- yani çekimli
    # hâli "isim" kökünü ÖNEK olarak İÇERMEZ ("ismi" 'isim' ile başlamaz).
    # Eski "isim\w*" deseni bu yüzden en yaygın kullanım olan "Ticari ismi :"
    # ile HİÇ eşleşmiyordu ve ürün adı çoğu zaman boş dönüyordu. "is(?:im\b|mi\w*)"
    # hem temel hem çekimli hâlleri kapsar.
    patterns = [
        r"Ürün\s+is(?:im\b|mi\w*)\s*:?\s*(.+)",
        r"Ticari\s+is(?:im\b|mi\w*)\s*:?\s*(.+)",
        r"Ticari ad[ıi]\s*:?\s*(.+)",
        r"Ürün ad[ıi]\s*:?\s*(.+)",
        r"Product\s*Name\s*:?\s*(.+)",  # İngilizce MSDS
        r"Trade\s*Name\s*:?\s*(.+)",    # "Trade Name: KROMOFIX..." İngilizce şablon
        r"(?m)^\s*[UÜ]nvan[ıi]\s+(.+?)\s*$",  # "Unvanı   LAUFIX E" sütun formatı (ERCA GROUP)
        r"\|\s*[UÜ]nvan[ıi]\s*\|\s*([^\n|]{2,90})\s*\|",  # "| Unvanı | CINDYE DNK |" pipe tablo formatı
        # BASF formatı: header'da "Ürün: Hydrosulfite F"
        r"(?m)^\s*Ürün:\s*(.+?)\s*$",
        # BASF şablonunda "Ürün:" satır başında olmayabilir (aynı satırda
        # "Revizyon: 9.0 Ürün: Hydrosulfite F (ID no. ...) Basım tarihi..."
        # gibi metaverilerle iç içe geçebilir) -- parantez veya iki
        # boşluktan önce durarak daha esnek şekilde yakala
        r"Ürün:\s*([^\n(]{2,60}?)\s*(?:\(|\s{2,}|$)",
        r"\|\s*Ürün\s*\|\s*ismi\s*\|\s*:?\s*\|\s*([^\n|]{2,90})\s*\|",  # "| Ürün | ismi | : | Iron(II)... |" 4 hücreli format
        r"\|\s*Ürün\s*\|\s*:?\s*([^\n|]{2,90})\s*\|",  # "| Ürün | : COMPLEXA DEMINERA |" pipe tablo formatı
        # "Ticaret Adı…...…:REACTIVE DEEP NIGHT SS CAS #..." -- nokta dolgulu
        # eski usül SHAH INDUSTRIES şablonu; "CAS" veya "Kimyasal Adı"
        # görülünce dur (aksi halde bunlar da değere karışır)
        r"Ticaret\s*Ad[ıi][.…\s]*:\s*([^\n]{2,80}?)\s*(?:CAS\b|Kimyasal\s*Ad|$)",
        # "| 1.1 Malzeme |  | Susuz Sodyum Karbonat |" -- bazı eski
        # şablonlarda ürün adı "Ürün"/"Ticari" değil "Malzeme" etiketiyle
        # geçiyor (Soda şablonu)
        r"\|\s*(?:\d\.\d\s*)?Malzeme\s*\|\s*\|?\s*([^\n|]{2,80})\s*\|",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            name = re.sub(r"™|®", "", name).strip()
            name = _pipe_ilk_hucre(name)
            name = _urun_adi_kirp(name)
            if name:
                return name
    return None


def find_section_text(text: str, section_no: int, next_section_no: int = None):
    """find_section14_text'in genel hâli -- herhangi bir bölüm numarasının
    metnini izole eder. Hem 'N.' hem 'BÖLÜM N:' hem 'KISIM N :' hem de
    noktasız 'N Başlık' stillerini tanır (üreticiye göre değişiyor)."""
    pattern = (rf"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*{section_no}"
               r"\s*(?:[-.:]\s*|\s+(?=[A-ZÇĞİÖŞÜa-zçğışöü]))")
    m_start = re.search(pattern, text)
    if not m_start:
        return None
    start = m_start.start()
    end_no = next_section_no if next_section_no else section_no + 1
    end_pattern = (rf"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*{end_no}"
                   r"\s*(?:[-.:]\s*|\s+(?=[A-ZÇĞİÖŞÜa-zçğışöü]))")
    m_end = re.search(end_pattern, text[start:])
    end = start + m_end.start() if m_end else min(len(text), start + 4000)
    return text[start:end]


_COMPANY_SUFFIX = r"(A\.?Ş\.?|Ltd\.?\s*Şti\.?|GmbH|Sanayi|San\.|Ticaret|Tic\.|Kimya|Inc\.|Corp\.|S\.A\.)"


def _pipe_ilk_hucre(deger: str) -> str:
    """Değer bir markdown '|' tablo satırı ise ('| CHT Germany GmbH |
    CHT Switzerland AG |' gibi), ilk dolu hücreyi döner. '|' içermeyen
    normal değerlerde hiçbir şey değişmez. Bazı PDF->metin dönüştürme
    araçları tablo hücrelerini '|' ile ayırdığından, etiketten sonra
    gelen ilk hücreyi (genelde asıl firma adı) tek başına almak,
    hücrenin tamamının ham '| A | B |' halinde yazılmasından daha
    doğrudur."""
    if not deger or "|" not in deger:
        return deger
    for hucre in deger.split("|"):
        hucre = hucre.strip(" -:")
        if hucre:
            return hucre
    return deger


_ETIKET_KELIME = re.compile(
    r"^(?:[Şşġ]irket|Firma|Tedarikçi|Unvan|Ad[ıi]|Adres|İsim|Name|Kod)\b", re.IGNORECASE
)


def _pipe_satir_deger(line: str) -> str:
    """'| Şirket Unvanı | ERCA GROUP... |' gibi tam olarak İKİ hücreli bir
    markdown tablo satırında, ilk hücre bir etiket kelimesiyle
    başlıyorsa İKİNCİ (değer) hücreyi döner. Diğer tüm durumlarda
    (örn. '| CHT Germany GmbH | CHT Switzerland AG |' gibi iki ayrı
    değerin yan yana durduğu satırlarda) davranış değişmez -- ilk dolu
    hücre döner (_pipe_ilk_hucre)."""
    if line.count("|") == 2 and line.strip().startswith("|") and line.strip().endswith("|"):
        hucreler = [h.strip(" -:") for h in line.strip().strip("|").split("|")]
        if len(hucreler) == 2 and hucreler[0] and _ETIKET_KELIME.match(hucreler[0]):
            return hucreler[1]
    return _pipe_ilk_hucre(line)


# Tedarikçi değeri olarak KABUL EDİLEMEZ kalıntılar. Bir desen etiketin
# kendisini ya da devamını yakalarsa hücrede firma adı yerine bunlar
# görünüyordu (örn. "/Üretici Tanımı").
_TEDARIKCI_GECERSIZ = [
    r"^[/\\|,;:.\-–\s]",                       # "/Üretici Tanımı" gibi ayraçla başlayan
    r"^(?:[üu]retici|tedarik[çc]i|firma|[şs]irket|imalat[çc][ıi])\b"
    r"[^\n]{0,25}(?:tan[ıi]m[ıi]?|bilgiler[ıi]?|ad[ıi]|unvan[ıi]?)\s*$",
    r"^(?:tan[ıi]m[ıi]?|bilgiler[ıi]?|ad[ıi]|unvan[ıi]?)\s*$",
    r"^(?:adres|telefon|faks|fax|tel|e-?posta|mail|web)\b",
    r"^(?:mevcut\s+de[ğg]il|bilgi\s+yok|veri\s+yok|belirtilmemi[şs])",
]


_TEDARIKCI_ETIKET_ONEKI = (
    r"^\s*(?:[şs]irket|firma|tedarik[çc]i|[üu]retici|imalat[çc][ıi]|"
    r"company|supplier|manufacturer)"
    r"(?:\s*/\s*(?:[üu]retici|tedarik[çc]i|supplier|manufacturer))?"
    r"(?:\s+(?:ad[ıi]|unvan[ıi]?|tan[ıi]m[ıi]?|bilgisi|bilgileri|name))?"
    r"\s*(?::|\s{2,})\s*"
)


def _tedarikci_temizle(val: str):
    """Değerin BAŞINA yapışmış etiketi temizler.
    "Şirket Adı        TEKKİM KİMYA..." -> "TEKKİM KİMYA..."
    """
    if not val:
        return val
    onceki = None
    while onceki != val:
        onceki = val
        yeni = re.sub(_TEDARIKCI_ETIKET_ONEKI, "", val, count=1, flags=re.IGNORECASE)
        if yeni.strip():
            val = yeni
    return re.sub(r"\s{2,}", " ", val).strip(" :|-–").strip()


def _tedarikci_gecersiz(val: str) -> bool:
    """Değer firma adı mı, yoksa etiket kalıntısı mı?"""
    d = re.sub(r"\s+", " ", str(val or "")).strip()
    if len(d) < 3:
        return True
    for p in _TEDARIKCI_GECERSIZ:
        if re.match(p, d, re.IGNORECASE):
            return True
    return False


def _tedarikci_aday(val):
    """Adayı temizler ve doğrular; geçerliyse döner, değilse None."""
    val = _tedarikci_temizle(_pipe_ilk_hucre(val))
    return None if _tedarikci_gecersiz(val) else val


def extract_tedarikci(text: str):
    """Bölüm 1.3'ten tedarikçi/üretici firma adını çıkarır.

    Sonuç, etiket kalıntısı olmadığından emin olmak için
    _tedarikci_gecersiz() ile son bir kez sınanır."""
    deger = _extract_tedarikci(text)
    return None if _tedarikci_gecersiz(deger) else deger


def _extract_tedarikci(text: str):
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    # "Firma Adı :" etiketi (örn. HABAŞ şablonu) -- bunu "Tedarikçi"
    # etiketinden ÖNCE deniyoruz çünkü "Tedarikçi" kelimesi genelde
    # "Tedarikçisinin Bilgileri" gibi bir başlığın içinde çekim ekiyle
    # geçer ve aşağıdaki "Tedarikçi" deseni o ekin devamını ("sinin
    # Bilgileri") yanlışlıkla firma adı diye yakalayabilir.
    m = re.search(r"Firma\s+Ad[ıi]\s*:?\s*\n?\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Şirket Unvanı   ERCA GROUP..." sütun formatı — etiket + büyük boşluk + değer
    m = re.search(r"[Şşġ]irket\s+[UÜ]nvan[ıi]\s{2,}([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "| Şirket Unvanı | ERCA GROUP... |" / "| Şirket Adı | TEKKİM... |" markdown
    # tablo formatı (tek boşluklu pipe hücreleri -- yukarıdaki 2+ boşluk
    # deseni bunu yakalamaz)
    m = re.search(r"[Şşġ]irket\s+(?:[UÜ]nvan[ıi]|Ad[ıi])\s*\|\s*([^\n|]{3,90})\s*\|", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Tedarikçi/Üretici Tanımı : ABC KİMYA" — BİLEŞİK etiket. Aşağıdaki
    # genel "Tedarikçi" deseni burada "Tedarikçi" kelimesini eşleştirip
    # etiketin GERİ KALANINI ("/Üretici Tanımı") firma adı sanıyordu.
    # Etiket, ":" ve değer AYRI SATIRLARDA da olabilir.
    m = re.search(
        r"(?:Tedarik[çc]i|[ÜU]retici)\s*/\s*(?:[ÜU]retici|Tedarik[çc]i)"
        r"(?:\s+(?:Tan[ıi]m[ıi]?|Bilgileri|Ad[ıi]|Firma\w*))?"
        r"\s*:?\s*\n?\s*:?\s*\n?\s*([^\n]{3,90})",
        bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Tedarikçi" etiketi -- yalnızca kelime sınırında bittiğinde
    # ("Tedarikçi :" veya "Tedarikçi\n") eşleştiriyoruz; "Tedarikçisinin"
    # gibi bir çekim ekiyle devam ediyorsa bu, başlığın bir parçasıdır,
    # değer etiketi değildir. (?!\s*/) ise "Tedarikçi/Üretici ..." gibi
    # BİLEŞİK etiketleri dışarıda bırakır -- onlar yukarıda ele alınır.
    m = re.search(r"Tedarikçi\b(?!sinin|nin|si)(?!\s*/)[\s|]*(?:Firma\w*)?[\s|]*:?[\s|]*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    m = re.search(r"Produc\w*\s+Company\s*\n?\s*([^\n]{3,90})", bolum1, re.IGNORECASE)  # İngilizce MSDS
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Şirket bilgisi: MKS DevO Kimya..." (MKS DevO şablonu)
    m = re.search(r"[Şşġ]irket\s+bilgisi\s*:?\s*([^\n]{3,90})", bolum1)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "| ġirket | : Huntsman Textile Effects |" -- çıplak "Şirket" etiketi,
    # pipe tablo formatında (bazı dönüştürme araçlarında Ş harfi bozuk
    # "ġ" karakterine dönüşüyor). Değer şirket soneki içermeyebilir
    # (ör. "Huntsman Textile Effects" -- Ltd/A.Ş./GmbH yok), bu yüzden
    # aşağıdaki 1.3 satır taraması (_COMPANY_SUFFIX gerektirir) bunu
    # yakalayamaz; doğrudan etiket eşleşmesi gerekir.
    m = re.search(r"[Şşġ]irket\s*\|\s*:?\s*([^\n|]{3,90})\s*\|", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Şirket     : Huntsman Textile Effects" -- Huntsman formatı (çok boşluk)
    m = re.search(r"[Şşġ]irket\s+:\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        deger = m.group(1).strip()
        # "Adres", "Telefon" gibi sonraki etiketler yakalanmadığını kontrol et
        if not re.match(r"(?i)Adres|Telefon|Fax", deger):
            _aday = _tedarikci_aday(deger)
            if _aday:
                return _aday
    # "Şirket Adı: Mavi Colour Kimya..." -- pipe olmayan düz metin formatı
    m = re.search(r"[Şşġ]irket\s+Ad[ıi]\s*:\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Manufacturer/ Supplier:\n\nCHT TURKEY..." -- İngilizce MSDS etiketi
    m = re.search(r"(?:Manufacturer\s*/\s*)?Supplier\s*:?[\s|]*([^\n|]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "...tedarikçisinin bilgileri Tekay Kimya Mümessillik ve Ticaret Ltd
    # Şti. İstanbul... Tel: +90..." -- başlık ve firma adı/adresi AYNI
    # paragrafta, hiçbir etiket veya "\n" olmadan birleşiyor (Tekay Kimya
    # şablonu). "Tel:"/"Fax:" sınırına kadar olan kısmı al.
    m = re.search(
        r"tedarikçisinin\s+bilgileri\.?\s*:?\s*([^\n]{3,150}?)\s*(?:Tel\s*[:.]|Fax\s*[:.]|GBF)",
        bolum1, re.IGNORECASE,
    )
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Firmanın Tanıtımı:\n\nMKS & DevO..." (eski MKS DevO / Complexa şablonu)
    m = re.search(r"Firman[ıi]n\s+Tan[ıi]t[ıi]m[ıi]\s*:\s*\n?\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "1.3 Şirketin Tanıtımı: YAR-KİM ENDÜSTRİYEL..." (SOL-5 şablonu)
    m = re.search(r"[Şşġ]irketin\s+Tan[ıi]t[ıi]m[ıi]\s*:\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "1.3 Üretici Adres: Soda Sanayii A.Ş. ..." (Soda şablonu -- "Adres"
    # etiketine rağmen değer firma adıyla başlıyor)
    m = re.search(r"Üretici\s+Adres\s*:\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "...Ayrıntılı Bilgileri Birpa Birlik Paz.Taah.Tic.Ltd.Şti Şirket :
    # Turgut Reis Mah..." -- bu şablonda firma adı "Ayrıntılı Bilgileri"
    # ile "Şirket :" etiketi arasında yer alır (alışılmadık sıra: "Şirket :"
    # etiketinin kendisi ADRES ile devam eder, firma adı değil).
    m = re.search(r"Ayr[ıi]nt[ıi]l[ıi]\s+Bilgileri\s+([^\n]{3,90}?)\s+Şirket\s*:", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    m = re.search(r"1\.3[.\s][^\n]*\n+((?:[^\n]+\n+){0,4})", bolum1)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line and re.search(_COMPANY_SUFFIX, line, re.IGNORECASE):
                # Satır "Şirket Adı   TEKKİM KİMYA ... LTD. ŞTİ" gibi ETİKETLE
                # başlıyor olabilir; _tedarikci_aday etiketi temizler.
                _aday = _tedarikci_aday(_pipe_satir_deger(line))
                if _aday:
                    return _aday
    # "1.3.1 ... tedarikçi bilgiler ; Firma Adı" — değer etiketle aynı satırda
    m = re.search(r"1\.3\.1[^\n]*tedarik\w*\s+bilgi\w*\s*;\s*([^\n]{3,90})", bolum1, re.IGNORECASE)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "Mümessil Firma\nFirma Adı" — Türkiye'deki yaygın format (Jay/Tekay şablonu)
    # Mümessil = yerel tedarikçi; üretici firma değil, biz onu alıyoruz.
    for aralik in [bolum1, text[:4000]]:
        m = re.search(r"Mümessil\s+Firma\s*\n?\s*([^\n]{3,90})", aralik, re.IGNORECASE)
        if m and m.group(1).strip():
            _aday = _tedarikci_aday(m.group(1).strip())
            if _aday:
                return _aday
    # "Üretici   HANGZHOU..." sütun formatı (MGVB/eski şablon — büyük boşluklu)
    for aralik in [bolum1, text[:2000]]:
        m = re.search(r"Üretici\s{2,}([^\n]{3,90})", aralik, re.IGNORECASE)
        if m and m.group(1).strip():
            _aday = _tedarikci_aday(m.group(1).strip())
            if _aday:
                return _aday
        m = re.search(r"Üretici\s+Firma\s*\n\s*([^\n]{3,90})", aralik, re.IGNORECASE)
        if m and m.group(1).strip():
            _aday = _tedarikci_aday(m.group(1).strip())
            if _aday:
                return _aday
    # Genel yedek: sadece "Şirket :" (başka özel etiket olmadan) --
    # başlıktaki "şirketin/dağıtıcının kimliği" ile karışmasın diye
    # zorunlu ":" gerektirir (başlıkta hemen ":" gelmez)
    m = re.search(r"\bŞirket\s*:\s*([^\n]{3,90})", bolum1)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
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


# Fonksiyon değerinin BAŞINA yapışmış etiket kalıntılarını temizleyen
# desenler. Bazı şablonlarda etiket ile değer AYNI SATIRDA olduğu için
# (sütun hizalı tablo ya da "etiket : değer" tek satır) yakalanan grup
# etiketi de içeriyordu:
#     "Madde/Müstahzarın : Tekstil boyaları, finisyon ve baskı ürünleri"
#     "Tanımlama/Kullanım    Nötrleştirici asit"
# Doğrusu yalnızca değerdir. Etiketin envantere yazılması hücreyi hatalı
# gösteriyordu.
_FONKSIYON_ETIKET_ONEKLERI = [
    # "Tanımlama/Kullanım <değer>" — iki nokta YOK, sütun boşluğu var.
    r"^\s*(?:tan[ıi]mlama|kullan[ıi]m)\s*/\s*(?:kullan[ıi]m[ıi]?|tan[ıi]mlama)\s*:?\s+",
    # "Madde/Müstahzarın Kullanımı <değer>" / "Madde/Karışımın kullanımı <değer>"
    r"^\s*madde(?:nin)?\s*/\s*(?:m[üu]stahzar[ıi]n|kar[ıi][şs][ıi]m[ıi]n)\s*(?:kullan[ıi]m[ıi]?)?\s*:?\s+",
    # "Ana kullanım kategorisi : <değer>" — etiket değere yapışmış.
    r"^\s*ana\s+kullan[ıi]m\s+kategorisi\s*:?\s+",
    # Tek başına "Kullanım" etiketi + SÜTUN BOŞLUĞU (2+ boşluk) ya da ":".
    # 2+ boşluk şartı bilinçli: "Kullanım kolaylığı sağlar" gibi GERÇEK bir
    # değer (tek boşluk) yanlışlıkla kırpılmasın.
    r"^\s*kullan[ıi]m[ıi]?\s*:\s+",
    r"^\s*kullan[ıi]m[ıi]?\s{2,}",
    # Genel: bilinen bir etiket kelimesiyle BAŞLAYIP ":" ile biten kısa
    # önek. Önekte VİRGÜL olmamalı — böylece "Ürün, tekstil boyamada
    # kullanılır: özellikle pamukta" gibi GERÇEK bir cümle yanlışlıkla
    # kırpılmaz (virgül cümle olduğunun işaretidir).
    r"^\s*(?:\d+(?:\.\d+)*\.?\s*)?"
    r"(?:madde|m[üu]stahzar|kar[ıi][şs][ıi]m|preparat|[üu]r[üu]n|malzeme|"
    r"tan[ıi]mlama|kullan[ıi]m|uygulama|belirlenmi[şs]|tavsiye|ana)"
    r"[^:\n,]{0,45}:\s*",
    # JENERİK KULLANIM KATEGORİSİ ÖNEKİ — "Endüstriyel Kullanım için
    # Organik boya" / "Endüstriyel kullanım. Bilimsel araştırma" /
    # "Endüstriyel Kullanım, Gıda ve Sanayi sektörü". Kategori ürünün
    # fonksiyonu değildir; ARDINDAN GELEN asıl açıklama korunur.
    # (Kategori TEK BAŞINA ise _fonksiyon_gecersiz onu zaten reddeder.)
    r"^\s*(?:end[üu]striyel|profesyonel|sanayi|t[üu]ketici|mesleki|"
    r"industrial|professional|consumer)\s+kullan[ıi]m\w*\s*"
    r"(?:i[çc]in|,|\.|:|;|-|–)\s+",
]

# Değer "veri yok" anlamına geliyorsa fonksiyon bilgisi YOKTUR -> "-" yazılır.
_VERI_YOK = [
    r"^mevcut\s+de[ğg]il", r"^bilgi\s+yok", r"^veri\s+yok",
    r"^bulunmayan\s+bilgiler", r"^belirtilmemi[şs]", r"^bilinmiyor",
    r"^not\s+available", r"^no\s+data", r"^n\s*/\s*a$", r"^-+$",
]


def _fonksiyon_temizle(val: str, kisalt: bool = True):
    """Yakalanan fonksiyon metninden etiket önekini ve fazla boşlukları
    temizler. Temizlik sonrası anlamlı bir değer kalmazsa None döner
    (böylece bir sonraki desen denenir, etiket envantere yazılmaz)."""
    if not val:
        return None
    onceki = None
    # Birden fazla önek üst üste gelebilir; değişim durana kadar tekrarla.
    while onceki != val:
        onceki = val
        for p in _FONKSIYON_ETIKET_ONEKLERI:
            yeni = re.sub(p, "", val, count=1, flags=re.IGNORECASE)
            if yeni != val and yeni.strip():
                val = yeni
                break
    # Sütun hizalamasından gelen çoklu boşlukları teke indir; baştaki/
    # sondaki artık noktalama işaretlerini (nokta, tire, iki nokta) at.
    val = re.sub(r"\s{2,}", " ", val).strip().strip("-–:.").strip()
    if kisalt:
        val = _fonksiyon_kisalt(val)
    return val or None


# "Fonksiyonu" sütununa YAZILMAMASI gereken JENERİK kullanım kategorileri.
# Bunlar ECHA maruziyet kategorileridir (kimi kullanıyor: sanayi/profesyonel/
# tüketici), ürünün NE İŞE YARADIĞINI söylemezler. MSDS Bölüm 1.2'de
# genellikle "Ana kullanım kategorisi : Endüstriyel kullanım" satırında
# geçerler ve asıl fonksiyon ("Maddenin/karışımın kullanımı : Reaktif boyar
# madde") BİR ALT satırdadır.
_JENERIK_KULLANIM = [
    r"^end[üu]striyel\s+kullan[ıi]m\w*$",
    r"^sanayi(?:de)?\s+kullan[ıi]m\w*$",
    r"^profesyonel\s+kullan[ıi]m\w*$",
    r"^t[üu]ketici\s+kullan[ıi]m\w*$",
    r"^mesleki\s+kullan[ıi]m\w*$",
    r"^industrial\s+use\w*$",
    r"^professional\s+use\w*$",
    r"^consumer\s+use\w*$",
]

# Değerin kendisi bir ETİKET ise (satır kaymasıyla etiket satırı değer
# sanılmışsa) reddedilir.
_ETIKET_SATIRI = [
    r"^ana\s+kullan[ıi]m\s+kategorisi$",
    r"^madde(?:nin)?\s*/\s*kar[ıi][şs][ıi]m[ıi]n\s+kullan[ıi]m[ıi]?$",
    r"^tan[ıi]mlama\s*/\s*kullan[ıi]m[ıi]?$",
    r"^kullan[ıi]m\s+alan[ıi]$",
    r"^belirlenmi[şs]\s+kullan[ıi]mlar[ıi]?$",
    r"^tavsiye\s+edilmeyen\s+kullan[ıi]mlar[ıi]?$",
]


def _fonksiyon_gecersiz(val: str) -> bool:
    """Değer jenerik bir kullanım kategorisi mi, etiket satırının kendisi
    mi, yoksa 'veri yok' anlamına mı geliyor? Öyleyse fonksiyon değeri
    sayılmaz (sonraki desen denenir, hiçbiri tutmazsa hücreye "-" yazılır)."""
    d = re.sub(r"\s+", " ", str(val or "")).strip().strip(":").strip()
    for p in _JENERIK_KULLANIM + _ETIKET_SATIRI + _VERI_YOK:
        if re.match(p, d, re.IGNORECASE):
            return True
    return False


# Kırpma eşiği: bu uzunluğu AŞAN fonksiyon metinleri, MSDS Bölüm 1.2'de
# çok maddeli bir kullanım listesi (";" veya "," ile ayrılmış) olduğu için
# ilk maddeye indirilir. Eşiğin altındaki değerlere DOKUNULMAZ -- örn.
# "Tekstil boyaları, finisyon ve baskı ürünleri - ağartıcı ve diğer" (63)
# ya da "Boya koruyucu, yükseltgen madde" (31) olduğu gibi kalır.
_FONKSIYON_KIRPMA_ESIGI = 70

# İlk maddenin SONUNDA kalan ve tek başına anlam taşımayan bağlaç/ek
# kelimeler ("... koruyucu gaz olarak" -> "... koruyucu gaz").
_FONKSIYON_SON_EKLER = (
    r"\s+(?:olarak|i[çc]in|amac[ıi]yla|kullan[ıi]l[ıi]r|"
    r"kullan[ıi]lmaktad[ıi]r|kullan[ıi]m[ıi]nda|ile)\s*$"
)


def _fonksiyon_kisalt(val: str) -> str:
    """Çok maddeli uzun kullanım listelerini ilk maddeye indirir.

    HABAŞ tarzı gaz MSDS'lerinde Bölüm 1.2 onlarca kullanım alanını tek
    paragrafta sayar; bunun tamamı envanter hücresine sığmaz ve okunmaz.
    Ayraç önceliği: ";" (güçlü madde ayracı) > ",".
    """
    if not val or len(val) <= _FONKSIYON_KIRPMA_ESIGI:
        return val
    for ayrac in (";", ","):
        if ayrac in val:
            ilk = val.split(ayrac)[0].strip()
            if len(ilk) >= 12:          # anlamlı bir madde mi?
                val = ilk
                break
    val = re.sub(_FONKSIYON_SON_EKLER, "", val, flags=re.IGNORECASE).strip()
    return val.strip(" ,;.-–:")


def extract_fonksiyon_ham(text: str):
    """extract_fonksiyon ile AYNI değeri döner ama ÇOK MADDELİ uzun liste
    KIRPILMADAN verilir. AI'nın (fonksiyon_sec) hangi maddeleri arasından
    seçim yapacağını görmesi için gereklidir."""
    return _extract_fonksiyon(text, kisalt=False)


def extract_fonksiyon(text: str):
    return _extract_fonksiyon(text, kisalt=True)


def _extract_fonksiyon(text: str, kisalt: bool = True):
    """Bölüm 1.2'den ürünün kullanım amacını/fonksiyonunu çıkarır.

    KRİTİK: Başlık numaralandırması ("1.2.1", "1.3" vb.) veya İngilizce
    metin (kaynak belge Türkçe değilse bile envanterde Türkçe açıklama
    beklenir) değer diye yakalanmasın; sadece Türkçe açıklayıcı fonksiyon
    metni dönsün, aksi halde None (elle doldurulacak) dönülür."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    patterns = [
        # EN YÜKSEK ÖNCELİK — "Maddenin/karışımın kullanımı : Reaktif boyar
        # madde". Bu etiket ürünün GERÇEK fonksiyonunu verir ve aynı 1.2
        # bloğunda yer alan "Ana kullanım kategorisi" (Endüstriyel/
        # Profesyonel kullanım) etiketinden ÖNCE denenmelidir -- yoksa
        # jenerik kategori değeri fonksiyon sanılıyordu.
        # Etiket, ":" ve değer AYRI SATIRLARDA olabilir:
        #     Maddenin/karışımın kullanımı
        #     :
        #     Reaktif boyar madde
        # Bu yüzden aralarda serbest satır sonu tolere edilir.
        r"(?i)Madde(?:nin)?\s*/\s*" + _esnek_desen("karışımın") + r"\s+"
        + _esnek_desen("kullanımı") + r"\s*:?\s*\n?\s*:?\s*\n?\s*([^\n]{3,200})",
        r"(?m)^\s*" + _esnek_desen("Belirlenmiş kullanımlar") + r"\b\s*:?\s*\n?\s*([^\n]{3,80})",
        r"(?m)^\s*" + _esnek_desen("Kullanım alanı") + r"\b\s*:\s*([^\n]{3,80})",
        # "| Kullanım Alanı | : Endüstriyel Kullanım için Organik boya. |"
        # pipe tablo formatı (Dyteks/ANTIQ şablonu) -- yukarıdaki satır-başı
        # deseni "|" ile başlayan hücreleri yakalayamaz.
        r"\bKullan[ıi]m\s+Alan[ıi]\s*\|\s*:?\s*([^\n|]{3,150})\s*\|",
        # "...tavsiye edilmeyen kullanımları Tavsiye edilen kullanım
        # alanı: Renklendirici/pigment..." -- etiket satır başında değil,
        # başlık cümlesinin devamında (Alptekindyes/ACRYLA şablonu).
        r"Tavsiye\s+edilen\s+kullan[ıi]m\s+alan[ıi]\s*:\s*([^\n]{3,150})",
        r"(?m)^\s*Kullanim\s*:\s*\n?\s*([^\n]{3,80})",
        r"Relevant\s+identified\s+uses\s*:\s*([^\n]{3,120})",  # İngilizce MSDS (satır başında olmayabilir)
        # "...belirlenmiş kullanımları ve tavsiye edilmeyen kullanımları
        # Madde/Karışımın kullanımı : Tekstil ..." -- başlık ve değer AYNI
        # satırda (CHT şablonu). Bu deseni, aşağıdaki genel/greedy son
        # desenden ÖNCE deniyoruz -- yoksa o greedy desen değeri "satırın
        # devamı" sayıp yutuyor, sonra YANLIŞLIKLA bir sonraki satırı
        # (örn. "1.3 Güvenlik bilgi formu...") fonksiyon diye yakalıyordu.
        r"(?i)Madde\s*/\s*" + _esnek_desen("Karışımın") + r"\s+" + _esnek_desen("kullanımı") + r"\s*:\s*([^\n]{3,200})",
        # "1.2.1. Tanımlanmış uygun kullanımlar\n\n| Ana kullanım kategorisi
        # | : Renklendirici/pigment... |" (Alptekindyes/ACRYLA/VINAZOL/POLY
        # şablonu). Bu deseni HABAŞ-tarzı genel yakalamadan (aşağıda) ÖNCE
        # deniyoruz -- yoksa o genel desen "1.2.1. Tanımlanmış uygun
        # kullanımlar" ALT BAŞLIĞININ KENDİSİNİ yanlışlıkla fonksiyon
        # metni sanıyordu.
        r"Ana\s+kullan[ıi]m\s+kategorisi\s*\|\s*:?\s*([^\n|]{3,150})\s*\|",
        r"Ana\s+kullan[ıi]m\s+kategorisi\s*:?\s*\n?\s*:?\s*\n?\s*([^\n]{3,150})",
        # HABAŞ tarzı şablon: başlık satırın ortasında geçiyor ("1.2.
        # Madde veya Karışımın Belirlenmiş Kullanımları ve Tavsiye
        # Edilmeyen Kullanımları") ve değer doğrudan ALT satırda, ayrı
        # bir etiket/iki nokta olmadan başlıyor. -- ÖNEMLİ: Yakalanan
        # değer "1.2.1." / "1.3" gibi başlık numarası İÇERMESİN.
        r"(?i)Belirlenmi[şs]\s+[Kk]ullan[ıi]mlar[ıi]?\b[^\n]*\n\s*([^\n]{3,200})",
    ]
    # İngilizce fonksiyon metnini eleyen anahtar kelimeler -- kaynak belge
    # İngilizce olsa bile bu alanda Türkçe açıklama beklenir; İngilizce
    # yakalanırsa None dönülür (elle doldurulur) ham İngilizce metin
    # gösterilmez.
    _ingilizce_anahtar = (
        r"\b(?:used|for|bleaching|material|fabric|washing|dyeing|finishing|"
        r"printing|textile|coating|chemical|process|treatment|as a|such as)\b"
    )
    for p in patterns:
        m = re.search(p, bolum1, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".")
            if not val:
                continue
            # Etiket kalıntısını ("Madde/Müstahzarın :", "Tanımlama/Kullanım")
            # değerin başından temizle -- bu kontrollerden ÖNCE yapılır ki
            # aşağıdaki başlık/İngilizce elemeleri gerçek değere uygulansın.
            val = _fonksiyon_temizle(val, kisalt=kisalt)
            if not val:
                continue
            # Jenerik kullanım kategorisi ("Endüstriyel kullanım") veya
            # etiket satırının kendisi ("Ana kullanım kategorisi") ise bu
            # fonksiyon DEĞİLDİR -- sıradaki deseni dene.
            if _fonksiyon_gecersiz(val):
                continue
            # "1.2.1" / "1.3" gibi bir sonraki bölüm başlık numarası
            # yakalanmışsa bu değer değildir, atla.
            if re.match(r"^\d+\.\d+", val) or val.startswith("1."):
                continue
            # "Tanımlanmış uygun kullanımlar" gibi alt başlığın kendisi
            # yakalanmışsa atla.
            if "Tanımlanmış" in val and len(val) < 20:
                continue
            if re.search(_ingilizce_anahtar, val, re.IGNORECASE):
                continue  # İngilizce metin -- sıradaki desene geç
            return val
    return None


def extract_cas_no(text: str):
    """Bölüm 3'ten CAS numarasını çıkarır. Karışımlarda birden fazla
    bileşen olabileceğinden, etiketli ilk eşleşme (veya genel CAS
    deseninin ilk örneği -- tablo düzenli MSDS'ler için yedek) alınır."""
    bolum3 = find_section_text(text, 3, 4)
    bolum1 = find_section_text(text, 1, 2) or text[:2000]

    for aralik in [bolum3, bolum1, text[:3000]]:
        if not aralik:
            continue
        m = re.search(r"CAS\s*[-_.]?\s*[Nn]umaras[ıi]\s*:?\s*(\d{2,7}-\d{2}-\d)", aralik)
        if m:
            return m.group(1)
        # "CAS No   2309-94-6" sütun formatı (MGVB şablonu — büyük boşluklu)
        m = re.search(r"CAS[\s.-]*[Nn]o\.?\s*(\d{2,7}-\d{2}-\d)", aralik)
        if m:
            return m.group(1)
        m = re.search(r"\b(\d{2,7}-\d{2}-\d)\b", aralik)  # tablo düzeni için genel yedek
        if m:
            return m.group(1)
        # Tiresiz CAS (örn. "32041630") — Bölüm 1 veya 3'te "CAS no/No." etiketi yanında
        m = re.search(r"CAS\s*[-_.]?\s*[Nn]o\.?\s*:?\s*(\d{6,10})\b", aralik)
        if m:
            return m.group(1)
    return None


def _cas_check_digit(cas: str) -> bool:
    """CAS Registry check-digit doğrulaması: son rakam, önceki rakamların
    sağdan sola i*d toplamının mod 10'una eşit olmalı. Telefon/fatura/
    revizyon numaralarını eler."""
    try:
        parts = cas.split("-")
        if len(parts) != 3:
            return False
        rakamlar = parts[0] + parts[1]
        toplam = sum((i + 1) * int(d) for i, d in enumerate(reversed(rakamlar)))
        return toplam % 10 == int(parts[2])
    except Exception:
        return False


def extract_cas_listesi(text: str):
    """V3 (Sentez TMGD+İSG) için: karışım ürünlerdeki TÜM bileşenlerin
    CAS numaralarını Bölüm 3'ten çıkarır. Tekil ürünlerde tek elemanlı
    liste, karışımlarda 2+ elemanlı liste döner. Check-digit ile geçersiz
    numaralar (telefon, fatura vs.) elenir; sıra korunur, tekrarlar
    silinir."""
    bolum3 = find_section_text(text, 3, 4) or ""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    bulunanlar = []
    seen = set()

    def _ekle(cas):
        if cas and cas not in seen and _cas_check_digit(cas):
            seen.add(cas)
            bulunanlar.append(cas)

    # 1) Bölüm 3'te etiketli tüm CAS'ler (karışım tablosu)
    for m in re.finditer(r"CAS[\s.\-_]*(?:[Nn]o\.?|[Nn]umaras[ıi]|[Nn]r\.?)?\s*:?\s*(\d{2,7}-\d{2}-\d)", bolum3):
        _ekle(m.group(1))
    # 2) Bölüm 3'te etiketsiz (tablo düzenli MSDS'ler)
    for m in re.finditer(r"\b(\d{2,7}-\d{2}-\d)\b", bolum3):
        _ekle(m.group(1))
    # 3) Yedek: Bölüm 1 (tek maddeli ürünlerde CAS burada olur)
    if not bulunanlar:
        for m in re.finditer(r"CAS[\s.\-_]*(?:[Nn]o\.?|[Nn]umaras[ıi]|[Nn]r\.?)?\s*:?\s*(\d{2,7}-\d{2}-\d)", bolum1):
            _ekle(m.group(1))
        for m in re.finditer(r"\b(\d{2,7}-\d{2}-\d)\b", bolum1):
            _ekle(m.group(1))
    return bulunanlar


def extract_uretici(text: str):
    """V3: Kimyasal Üretici Firma Adı — Bölüm 1'de tedarikçiden AYRI
    olarak listelenen üreticiyi çıkarır. Türkiye MSDS'lerinde tipik
    örüntü: 'Üretici Firma\\n[İsim]' veya 'Manufacturer: [İsim]'. Eğer
    ayrı üretici yoksa None döner (o durumda tedarikçi = üretici kabul
    edilebilir; app'te fallback yaparız)."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    patterns = [
        # EN YÜKSEK ÖNCELİK — "Maddenin/karışımın kullanımı : Reaktif boyar
        # madde". Bu etiket ürünün GERÇEK fonksiyonunu verir ve aynı 1.2
        # bloğunda yer alan "Ana kullanım kategorisi" (Endüstriyel/
        # Profesyonel kullanım) etiketinden ÖNCE denenmelidir -- yoksa
        # jenerik kategori değeri fonksiyon sanılıyordu.
        # Etiket, ":" ve değer AYRI SATIRLARDA olabilir:
        #     Maddenin/karışımın kullanımı
        #     :
        #     Reaktif boyar madde
        # Bu yüzden aralarda serbest satır sonu tolere edilir.
        r"(?i)Madde(?:nin)?\s*/\s*" + _esnek_desen("karışımın") + r"\s+"
        + _esnek_desen("kullanımı") + r"\s*:?\s*\n?\s*:?\s*\n?\s*([^\n]{3,200})",
        r"(?i)Üretici\s+Firma\s+Ad[ıi]\s*:?\s*\n?\s*([^\n]{3,90})",
        r"(?i)Üretici\s+Firma\s*\n\s*([^\n]{3,90})",
        r"(?i)Üretici\s*:?\s*\n?\s*([^\n]{3,90})",
        r"(?i)İmalatç[ıi]\s+Firma\s*:?\s*\n?\s*([^\n]{3,90})",
        r"(?i)İmalatç[ıi]\s*:?\s*\n?\s*([^\n]{3,90})",
        r"(?i)Manufacturer\s*:?\s*\n?\s*([^\n]{3,90})",
        r"(?i)Producer\s*:?\s*\n?\s*([^\n]{3,90})",
    ]
    for p in patterns:
        m = re.search(p, bolum1)
        if m and m.group(1).strip():
            deger = m.group(1).strip()
            # "Tedarikçi" başlığından değere sıçramış olmasın kontrolü.
            # "Üretici/Tedarikçi" gibi BİRLEŞİK başlıklarda (ayrı üretici
            # bilgisi olmayan CHT tarzı şablonlar) "Üretici" sonrası
            # doğrudan "/Tedarikçi" veya "/Tedarikçisinin detayları" gelir
            # -- bu bir değer değil, başlığın devamıdır.
            if not re.match(r"(?i)/?\s*(Tedarikçi|Supplier)|Firma\s+Ad|Adres", deger):
                _aday = _tedarikci_aday(deger)
                if _aday:
                    return _aday
    return None


def extract_urun_kodu(text: str):
    """V3: Ürün Kodu — Bölüm 1'deki 'Ürün Kodu', 'Ürün No', 'Product Code',
    'Article No', 'Katalog No' gibi etiketli değerler."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    patterns = [
        # EN YÜKSEK ÖNCELİK — "Maddenin/karışımın kullanımı : Reaktif boyar
        # madde". Bu etiket ürünün GERÇEK fonksiyonunu verir ve aynı 1.2
        # bloğunda yer alan "Ana kullanım kategorisi" (Endüstriyel/
        # Profesyonel kullanım) etiketinden ÖNCE denenmelidir -- yoksa
        # jenerik kategori değeri fonksiyon sanılıyordu.
        # Etiket, ":" ve değer AYRI SATIRLARDA olabilir:
        #     Maddenin/karışımın kullanımı
        #     :
        #     Reaktif boyar madde
        # Bu yüzden aralarda serbest satır sonu tolere edilir.
        r"(?i)Madde(?:nin)?\s*/\s*" + _esnek_desen("karışımın") + r"\s+"
        + _esnek_desen("kullanımı") + r"\s*:?\s*\n?\s*:?\s*\n?\s*([^\n]{3,200})",
        r"(?i)Ürün\s+Kodu\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
        r"(?i)Ürün\s+No\.?\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
        r"(?i)Product\s+Code\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
        r"(?i)Product\s+No\.?\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
        r"(?i)Article\s+(?:No\.?|Number)\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
        r"(?i)Katalog\s+No\.?\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
        r"(?i)Malzeme\s+No\.?\s*:?\s*([A-Za-z0-9][\w\-./]{1,40})",
    ]
    for p in patterns:
        m = re.search(p, bolum1)
        if m:
            kod = m.group(1).strip().rstrip(".,;:")
            # Salt sayı değilse veya en az bir harf/tire içeriyorsa ürün kodu kabul et
            if re.search(r"[A-Za-z\-]", kod):
                return kod
    return None


def extract_kimyasalin_turu(text: str):
    """V3: Kimyasalın Türü — MSDS Bölüm 1.2'deki tanım/kullanım metninden
    ürünün genel kategorisini çıkarır (tampon asit, enzim, boya, iyon
    dengeleyici, vs.). extract_fonksiyon ile örtüşür ama fonksiyon uzun
    kullanım açıklamasıdır; tür daha kısa/kategorik olmalı. Yaygın
    kategori sözcüklerini regex ile ara, yoksa None."""
    bolum1 = find_section_text(text, 1, 2) or text[:3000]
    # KRİTİK: Türkçe MSDS'lerin standart Bölüm 1 başlığı "...Şirketin /
    # Dağıtıcının Kimliği" şeklindedir -- bu başlıktaki "Dağıtıcının" kelimesi
    # "dispersan" anlamındaki "dağıtıcı" deseniyle eşleşiyor ve düzeltilmeden
    # önce HEMEN HEMEN HER Türkçe MSDS (argon gazından pigmente kadar) yanlış
    # şekilde "DİSPERSAN" olarak etiketleniyordu. Başlık satırını (ilk
    # "KİMLİĞİ" kelimesine kadar olan kısmı) örüntü aramasından önce kırp.
    bolum1_arama = re.sub(r"(?is)^.{0,150}?kimliği\s*", "", bolum1, count=1)
    # Yaygın Türkçe/İngilizce kimyasal tür anahtar kelimeleri (tekstil ağırlıklı)
    turler = [
        (r"(?i)tampon\s+asit", "TAMPON ASİT"),
        (r"(?i)tampon\s+alkali", "TAMPON ALKALİ"),
        (r"(?i)\bpH\s+düzenleyici", "pH DÜZENLEYİCİ"),
        (r"(?i)ıslat[ıi]c[ıi]", "ISLATICI"),
        (r"(?i)yumuşat[ıi]c[ıi]", "YUMUŞATICI"),
        (r"(?i)dispersan|dağıt[ıi]c[ıi]", "DİSPERSAN"),
        (r"(?i)sabitleyici|fiksatör", "SABİTLEYİCİ"),
        (r"(?i)ağart[ıi]c[ıi]|bleach", "AĞARTICI"),
        (r"(?i)indirgen|reducing\s+agent", "İNDİRGEN"),
        (r"(?i)yükseltgen|oxidizing\s+agent", "YÜKSELTGEN"),
        (r"(?i)\benzim\b|\benzyme\b", "ENZİM"),
        (r"(?i)boya(?:r\s+madde)?|\bdye\b", "BOYA"),
        (r"(?i)pigment", "PİGMENT"),
        (r"(?i)çözücü|solvent", "ÇÖZÜCÜ"),
        (r"(?i)deterjan|detergent", "DETERJAN"),
        (r"(?i)köpük\s+kesici|antifoam|defoamer", "KÖPÜK KESİCİ"),
        (r"(?i)yüzey\s+aktif|surfactant", "YÜZEY AKTİF"),
        (r"(?i)katalizör|catalyst", "KATALİZÖR"),
        (r"(?i)koruyucu\s+madde|preservative|biocide|biyosit", "KORUYUCU/BİYOSİT"),
        (r"(?i)şelatlay[ıi]c[ıi]|chelating\s+agent", "ŞELATLAYICI"),
    ]
    for desen, etiket in turler:
        if re.search(desen, bolum1_arama):
            return etiket
    return None


# MSDS dili tespiti için yaygın belirteç kelimeler (sadece o dilde geçer)
_DIL_BELIRTECI = {
    "TÜRKÇE":    [r"\bGüvenlik\s+Bilgi\s+Formu\b", r"\bTehlike\s+ifadeler[ıi]?\b",
                  r"\bZararl[ıi]l[ıi]k\b", r"\bTedarikçi\b", r"\bAmbalajlama\b"],
    "İNGİLİZCE": [r"\bSafety\s+Data\s+Sheet\b", r"\bHazard\s+statements?\b",
                  r"\bClassification\b", r"\bSupplier\b", r"\bIdentification\b"],
    "ALMANCA":   [r"\bSicherheitsdatenblatt\b", r"\bGefahrenhinweise\b",
                  r"\bZusammensetzung\b", r"\bLieferant\b"],
    "FRANSIZCA": [r"\bFiche\s+de\s+données\s+de\s+sécurité\b", r"\bMentions?\s+de\s+danger\b",
                  r"\bFournisseur\b"],
    "İTALYANCA": [r"\bScheda\s+di\s+dati\s+di\s+sicurezza\b", r"\bIndicazioni?\s+di\s+pericolo\b"],
    "İSPANYOLCA": [r"\bFicha\s+de\s+datos\s+de\s+seguridad\b", r"\bIndicaciones\s+de\s+peligro\b"],
}


def extract_msds_dili(text: str):
    """V3: MSDS/TDS Dili — belge dilini yaygın etiket kelimelerin frekansına
    bakarak tespit eder. En çok eşleşen dil kazanır; hiçbir dilde eşleşme
    yoksa None döner."""
    if not text:
        return None
    ornek = text[:5000]  # ilk 5000 karakter yeterli (başlıklar burada)
    puanlar = {}
    for dil, desenler in _DIL_BELIRTECI.items():
        # re.IGNORECASE — MSDS başlıkları BÜYÜK HARF olabilir ("GÜVENLİK BİLGİ FORMU")
        puan = sum(1 for d in desenler if re.search(d, ornek, re.IGNORECASE))
        if puan > 0:
            puanlar[dil] = puan
    if not puanlar:
        return None
    # En yüksek puanlı dili döndür
    return max(puanlar.items(), key=lambda kv: kv[1])[0]


def extract_h_kodlari(text: str):
    """Bölüm 2'den zararlılık kodlarını çıkarır, tekilleştirir.

    Hem H kodları (H317, H318+H319 ...) hem de EUH kodları (EUH014,
    EUH208 ...) yakalanır. ESKİ DAVRANIŞ: yalnızca `\\bH\\d{3}\\b` aranıyordu;
    "EUH208" içindeki "H208" kelime sınırı nedeniyle eşleşmediğinden EUH
    kodları HİÇ yakalanmıyor, alan boş kalıyor ve AI katmanına düşüyordu --
    AI de yalnızca EUH kodlarını yazıp gerçek H kodlarını atlayabiliyordu.

    Sıralama: önce gerçek H kodları, sonra EUH kodları (envanterde asıl
    sınıflandırma önce görünsün).

    EUH210 / EUH401 bilgi amaçlıdır (zararlılık ifadesi değil) ve elenir."""
    bolum2 = find_section_text(text, 2, 3) or text
    try:
        from ai_destek import BILGI_AMACLI_EUH
    except Exception:
        BILGI_AMACLI_EUH = frozenset({"EUH210", "EUH401"})

    h_kodlari, euh_kodlari = [], []
    # (?<![A-Za-z]) : "EU" ön ekini yakalamadan H kodunu ayırt eder;
    # EUH ayrı grup olarak ele alınır.
    for m in re.finditer(r"\b(EUH\d{3}|H\d{3}(?:\+H\d{3})*)\b", bolum2):
        kod = m.group(1).upper()
        if kod in BILGI_AMACLI_EUH:
            continue
        hedef = euh_kodlari if kod.startswith("EUH") else h_kodlari
        if kod not in hedef:
            hedef.append(kod)

    seen = h_kodlari + euh_kodlari
    return ", ".join(seen) if seen else None


def extract_uyari_kelimesi(text: str):
    """Bölüm 2.2'den Uyarı Kelimesi'ni (Tehlike/Dikkat) çıkarır."""
    bolum2 = find_section_text(text, 2, 3) or text
    m = re.search(r"Uyar[ıi]\s+[Kk]elimesi\s*:?\s*\n?\s*([^\n]{2,30})", bolum2)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    m = re.search(r"İşaret\s+[Kk]elime\w*\s*:?\s*\n?\s*([^\n]{2,30})", bolum2)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # "İşaret Sözcüğü :" etiketi (örn. HABAŞ şablonu) -- "Kelime" yerine
    # eş anlamlı "Sözcük" kelimesi kullanılıyor.
    m = re.search(r"İşaret\s+[Ss]özc[üu][ğg][üu]\s*:?\s*\n?\s*([^\n]{2,30})", bolum2)
    if m and m.group(1).strip():
        _aday = _tedarikci_aday(m.group(1).strip())
        if _aday:
            return _aday
    # BASF formatı: "Sinyal kelime:\nTehlike" — etiket alt satırda
    m = re.search(r"Sinyal\s+kelime\s*:?\s*\n?\s*(Tehlike|Dikkat)\b", bolum2, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # İngilizce MSDS: "Signal Word: Attention/Warning/Danger" → Türkçe karşılığa çevir
    m = re.search(r"Signal\s+Word\s*:?\s*\n?\s*(Attention|Warning|Danger)\b", bolum2, re.IGNORECASE)
    if m:
        return {"attention": "Dikkat", "warning": "Dikkat", "danger": "Tehlike"}.get(m.group(1).lower(), m.group(1))
    return None


def extract_tehlikeli_tehlikesiz(text: str, h_kodlari):
    """H kodu bulunduysa 'Tehlikeli', Bölüm 2 (Zararlılık Tanımlaması) açıkça
    sınıflandırılmamış/tehlikesiz diyorsa 'Tehlikesiz' döner; aksi halde
    belirsizdir (None).

    MSDS'lerde "tehlikesiz" ifadesi çok farklı biçimlerde geçebilir, bu
    yüzden tek bir sabit cümle yerine birkaç yaygın varyasyon kontrol
    edilir: "zararlı/tehlikeli olarak sınıflandırılmamıştır", tek başına
    "sınıflandırılmamıştır", "sınıflandırma kriterlerini karşılamamaktadır",
    "tehlikeli/zararlı değildir" gibi."""
    if h_kodlari:
        return "Tehlikeli"
    bolum2 = find_section_text(text, 2, 3) or text
    tehlikesiz_kaliplari = [
        # "zararlı/tehlikeli (madde/karışım) (olarak) sınıflandırılmamıştır"
        r"(zararl[ıi]|tehlikeli)\s+(madde\s+veya\s+kar[ıi][şs][ıi]m[ıi]?\s+|madde\s+|kar[ıi][şs][ıi]m\s+)?(olarak\s+)?s[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r",
        # Tek başına "sınıflandırılmamıştır" (Bölüm 2 sınıflandırma başlığı altında)
        r"\bs[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r\b",
        # "sınıflandırma kriterlerini karşılamamaktadır/karşılamıyor"
        r"s[ıi]n[ıi]fland[ıi]rma\s+kriterlerini\s+kar[şs][ıi]lam[ıi](yor|amaktad[ıi]r)",
        r"kriterlerini\s+kar[şs][ıi]lamamaktad[ıi]r",
        # "tehlikeli/zararlı değildir"
        r"(tehlikeli|zararl[ıi])\s+de[ğg]ildir",
    ]
    for kalip in tehlikesiz_kaliplari:
        if re.search(kalip, bolum2, re.IGNORECASE):
            return "Tehlikesiz"
    return None


def extract_full_info(pdf_path: str, text: str = None, ai_chain: list = None,
                       ai_models: dict = None, ai_keys: dict = None, ai_ollama_url: str = ""):
    """Bölüm 14 dışında, envanterin diğer sütunları için de Bölüm 1/2/3'ten
    bilgi çıkarır. extract_adr_info ile aynı metni tekrar okumamak için
    text önceden çıkarılmışsa parametre olarak verilebilir.

    ai_chain verilmezse (None/boş liste) davranış TAMAMEN eskisiyle aynıdır —
    sadece regex çalışır. ai_chain doluysa (kullanıcı en az bir API anahtarı
    girdiyse), regex'in BOŞ bıraktığı alanlar için AI tamamlayıcı katman
    devreye girer; regex'in doldurduğu hiçbir alana dokunulmaz."""
    if text is None:
        text = pdf_to_text(pdf_path)
    h_kodlari = extract_h_kodlari(text)
    sonuc = {
        "tedarikci": extract_tedarikci(text),
        "fonksiyon": extract_fonksiyon(text),
        # Kırpılmamış hali — AI seçimi (B) bunun üzerinden çalışır.
        "fonksiyon_ham": extract_fonksiyon_ham(text),
        "cas_no": extract_cas_no(text),
        "h_kodlari": h_kodlari,
        "tehlikeli_tehlikesiz": extract_tehlikeli_tehlikesiz(text, h_kodlari),
        "tehlike_etiketi": extract_uyari_kelimesi(text),
        "revize_tarihi": extract_revize_tarihi(text),
        # V3 (Sentez TMGD+İSG) alanları — V1/V2'yi hiç etkilemez, sadece
        # ek alan ekler. build_inventory_row_v3 bunları okur, V1/V2
        # ise "cas_no"/"tedarikci" gibi mevcut alanları okumaya devam eder.
        "uretici": extract_uretici(text),
        "urun_kodu": extract_urun_kodu(text),
        "kimyasalin_turu": extract_kimyasalin_turu(text),
        "msds_dili": extract_msds_dili(text),
        "cas_listesi": extract_cas_listesi(text),
    }

    if ai_chain:
        try:
            from ai_destek import tamamla_eksik_alanlar
            guncelleme = tamamla_eksik_alanlar(
                text, sonuc, chain=ai_chain, models=ai_models or {},
                keys=ai_keys or {}, ollama_url=ai_ollama_url,
            )
            sonuc.update(guncelleme)  # sadece AI'nın doldurabildiği (regex'in boş bıraktığı) alanlar
        except Exception:
            pass  # AI katmanı hiçbir koşulda regex sonucunu düşürmemeli

        # ── (B) Çok maddeli uzun kullanım listesinden AI ile SEÇİM ──────
        # Otomatik kırpma her zaman ilk maddeyi alır; ilk madde her zaman
        # en temsil edici olan değildir. AI listeden BİREBİR seçer ve
        # seçimi belgeye karşı doğrulanır. Başarısız olursa kırpılmış
        # değer (A) olduğu gibi kalır.
        ham = sonuc.get("fonksiyon_ham")
        if ham and len(ham) > _FONKSIYON_KIRPMA_ESIGI:
            try:
                from ai_destek import fonksiyon_sec
                secim = fonksiyon_sec(ham, chain=ai_chain, models=ai_models or {},
                                       keys=ai_keys or {}, ollama_url=ai_ollama_url)
                if secim:
                    sonuc["fonksiyon"] = secim
            except Exception:
                pass

    return sonuc


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
    pattern = r"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*14\s*(?:[-.:]\s*|\s+(?=[A-ZÇĞİÖŞÜa-zçğışöü]))"
    m_start = re.search(pattern, text)
    if not m_start:
        # Fallback: başlık resimde kalmış olabilir; ilk "14.1" alt başlığından itibaren al
        m_start = re.search(r"(?im)^\s*14\.1\b", text)
        if not m_start:
            return None
    start = m_start.start()
    end_pattern = r"(?im)^\s*(?:B[ÖO]L[ÜU]M|KISIM|SECTION)?\s*15\s*(?:[-.:]\s*|\s+(?=[A-ZÇĞİÖŞÜa-zçğışöü]))"
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
    r"(te[hk]likeli\s+(madde|mal)|ta[şs][ıi]mac[ıi]l[ıi][ğg]?[ıi]?|nakliye|ADR|RID|IMDG|IATA)"
    r"[^.\n]{0,60}?kapsam\w*\s+(de|dı)[ğg]?ildir",
    r"(te[hk]likeli\s+(madde|mal)|ta[şs][ıi]mac[ıi]l[ıi][ğg]?[ıi]?|nakliye|ADR|RID|IMDG|IATA)"
    r"[^.\n]{0,60}?kapsam\w*\s+dı[şs][ıi]ndad[ıi]r",
    r"te[hk]likeli\s+madde\s+(de|dı)[ğg]?ildir",
    r"te[hk]likeli\s+mal\s+(de|dı)[ğg]?ildir",                       # "Tehlikeli mal değildir"
    r"te[hk]likeli\s+(?:madde|ürün|mal)?\s*olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lma(?:m[ıi][şs]t[ıi]r|maktad[ıi]r)",
    r"te[hk]likeli\s+(?:madde\s+)?olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lmaz",   # "...sınıflandırılmaz" (geniş zaman, Jakazol formatı)
    r"te[hk]likeli\s+kimyasal\s+madde\s+olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r",  # "tehlikeli kimyasal madde olarak..."
    # "Taşıma yönetmelik kapsamında tehlikeli olarak sınıflandırılmamıştır"
    r"ta[şs][ıi]ma\s+yönetmelik\s+kapsam[ıi]nda\s+te[hk]likeli\s+olarak\s+s[ıi]n[ıi]fland[ıi]r[ıi]lmam[ıi][şs]t[ıi]r",
    r"te[hk]likeli\s+madde\s+olarak\s+düzenlenmemi[şsĢģ]t[ıi]r",        # "Tehlikeli madde olarak düzenlenmemiştir" (Ģ: CHT font bozulması)
    r"te[hk]likeli\s+madde\s+s[ıi]n[ıi]f[ıi]na\s+girmez",             # "...tehlikeli madde sınıfına girmez"
    r"\bdüzenleme\s+yoktur\b",                                     # "Düzenleme yoktur"
    r"s[ıi]n[ıi]fland[ıi]rma\s+belirtilmemi[şsĢģ]tir",           # "Sınıflandırma belirtilmemiştir" (Ģ: CHT font bozulması)
    r"s[ıi]n[ıi]fland[ıi]rma\s+yap[ıi]lmam[ıi][şsĢģ]t[ıi]r",   # "Sınıflandırma Yapılmamıştır" (Everlight şablonu)
    r"s[ıi]n[ıi]fland[ıi]r[ıi]lm[ıi][şsĢģ]\s+de[ğg]ildir",      # "Sınıflandırılmış değildir" (karayolu/demiryolu notları)
    r"ta[şsĢģ][ıi]mad[ae]\s+tehlikesiz",                          # "taşımada tehlikesiz ürün" (ADR/RID - sınıfı: - formatı)
    r"ADR[\w/\-]*\s*[-–]\s*s[ıi]n[ıi]f[ıi]\s*:\s*-",             # "ADR/RID - sınıfı: -" (tire = sınıf yok)
    # İngilizce MSDS'lerde görülen açık "kapsam dışı" ifadeleri
    r"not\s+(?:included|classified)\s+(?:as\s+)?(?:any\s+)?(?:dangerous\s+goods|transport\s+class)",
    r"not\s+regulated\s+(?:for|as)\s+transport",
    r"not\s+regulated\s+as\s+(?:a\s+)?dangerous",   # "Not regulated as a dangerous good/goods" veya "as dangerous goods"
    r"no(?:t)?\s+dangerous\s+goods\s+(?:for|in)\s+transport",
    r"not\s+dangerous\s+goods\b",                                  # "Not dangerous goods"
    r"not\s+a\s+dot\s+controlled\s+material",                      # ABD DOT formatı
    # "ADR Kısıtlama yoktur" formatı — yalnızca ADR satırına bakıyoruz.
    # RID/IMDG/IATA satırları bizim alanı etkilemez; sadece ADR satırı
    # "yoktur" diyorsa ürün ADR kapsamı dışındadır.
    r"(?m)^\s*ADR\s+K[ıi]s[ıi]tlama\s+yoktur",
    # "ADR Sınırlı değil" formatı — eski MGVB şablonları (Hangzhou/Jihua tarzı)
    r"(?m)^\s*ADR\s+S[ıi]n[ıi]rl[ıi]\s+de[ğg]il",
    # "ADR : Not classified as hazardous." — İngilizce Tekay şablonu
    r"(?m)^\s*ADR\s*:\s*Not\s+classified\s+as\s+hazardous",
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
    # DOTALL + .{0,200}? (eski [.\s:]* yerine): bazı şablonlarda etiketle
    # değer arasında "veya ID numarası" gibi ek metin VE bir satır sonu
    # oluyor ("14.1. UN numarası veya ID numarası\nUygulanmaz" — Setaş
    # çok modlu tablo formatı); ayrıca layout=True çıktısında sütun
    # hizalaması için etiketle değer arasına onlarca boşluk eklenebiliyor
    # (5 sütunlu ADR/IMDG/IATA/ADN/RID tablosunda 80+ karakter ölçüldü) --
    # eski desen satır atlayamıyordu VE bu kadar uzun boşluğu kapsamıyordu.
    m = re.search(
        r"(?:14\s*\.?\s*1\b\.?\s*)?UN[\s-]*(?:NUMARAS[ıi]|NO\.?|\([^)]*\)\s*number)"
        r".{0,200}?"
        r"\b(N\s*/\s*A|YOK|UYGULAN[AM]*Z|NONE|-)\b",
        section14_text, re.IGNORECASE | re.DOTALL)
    if m:
        return True
    return False


def _sec14_normalize(sec14_text: str) -> str:
    """KÖK NEDEN DÜZELTMESİ — pdfplumber layout modunda her satırı sabit
    genişliğe (~80-82 karakter) SAĞDAN BOŞLUKLA DOLDURUR. Bu dolgu,
    bu modüldeki tüm mesafe pencerelerini (.{0,150}, .{0,200}, .{0,300})
    şişirip eşleşmeleri kaçırıyordu:

        '     14.1. UN numarası<60 boşluk>\\n<82 boşluk>\\n   ADR/RID: UN 3265'

    Etiket ile değer arası GÖRSEL olarak 2 satır, ama KARAKTER olarak
    230+ -- yani pencereye sığmıyor ve UN no bulunamıyor, ürün
    "MANUEL KONTROL GEREKLİ" olarak işaretleniyordu (Argon/HABAŞ,
    CINDYE DNK/ERCA, FORACID TA/FOURKIM şablonlarında doğrulandı).

    Çözüm: satır sonu dolgularını at, satır içi boşluk dizilerini en
    fazla 2'ye indir. Satır YAPISI (\\n'ler) korunur -- find_adr_block ve
    satır bazlı desenler etkilenmez; yalnızca yapay karakter mesafesi
    ortadan kalkar."""
    if not sec14_text:
        return sec14_text
    satirlar = []
    for satir in sec14_text.split("\n"):
        satir = satir.replace("\xa0", " ").rstrip()
        # Satır içi uzun boşluk dizileri (sütun hizalaması) 2 boşluğa
        # indirilir -- sütun sınırı sinyali korunur, şişme kaybolur.
        satir = re.sub(r" {3,}", "  ", satir)
        satirlar.append(satir)
    return "\n".join(satirlar)


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
            # "UN numarası\nADR/RID: 1805 IMDG: 1805" formatı — başlık
            # numarasız, değer ADR/RID: etiketi ile geliyor.
            m = re.search(
                r"[ÜU]N\s+numara[sş][ıi]\s*\n\s*ADR[/\w]*\s*:\s*(\d{3,4})\b",
                sec14_text, re.IGNORECASE)
            if m:
                un_no = m.group(1)
            else:
                # "UN-numarası\nUN1384" formatı — başlık alt satırda
                # "UN<rakam>" şeklinde birleşik yazılmış (tire ile de olabilir).
                m = re.search(
                    r"[ÜU]N[-\s]*numara[sş][ıi]\s*\n\s*[ÜU]N\s*[-]?\s*(\d{3,4})\b",
                    sec14_text, re.IGNORECASE)
                if m:
                    un_no = m.group(1)
                else:
                    # "ADR / RID, IMDG, IATA:   3082" sütun formatı
                    # (ERCA GROUP şablonu — 14.1 altında mod listesi + değer)
                    m = re.search(
                        r"ADR\s*/\s*RID[^:\n]*:\s*(\d{3,4})\b",
                        sec14_text, re.IGNORECASE)
                    if m:
                        un_no = m.group(1)
                    else:
                        # "UN Numarası\n:\nUN 1072" formatı — etiket, ":" ve
                        # değer 3 AYRI satırda (14.1. ADR: alt başlığı,
                        # pdfplumber'ın sütunları alt alta dizdiği tablo).
                        # AYRICA "UN Numarası : UN 1006" (etiket, ":" ve
                        # değer AYNI satırda — HABAŞ/Argon şablonu, 14.1
                        # başlığı "ADR:" olduğu için 14.1 kalıbı tutmaz).
                        # ":" ve satır sonu ikisi de opsiyonel/serbest
                        # sırada tolere edilir.
                        m = re.search(
                            r"[ÜU]N\s*Numaras[ıi]\s*:?\s*(?:\n\s*)?:?\s*"
                            r"(?:[ÜU]N\s*)?(\d{3,4})\b",
                            sec14_text, re.IGNORECASE)
                        if m:
                            un_no = m.group(1)
                        else:
                            # "UN Numarası\n...\nUN No. (ADR/RID/ADN)
                            # UN1384" formatı — etiket satırından sonra bir
                            # ARA ETİKET daha var, ve sayı "UN" harflerine
                            # BİTİŞİK yazılmış (boşluksuz: "UN1384").
                            # \b\d{3,4}\b harf-rakam arasında \b bulamadığı
                            # için genel "UN NO." deseni bunu YAKALAYAMIYOR
                            # (harf ve rakam ikisi de \w sayıldığından
                            # aralarında word-boundary yok) -- bu ciddi bir
                            # güvenlik riski: gerçekten ADR kapsamındaki bir
                            # madde (örn. UN1384, Sınıf 4.2) sessizce
                            # atlanabilir.
                            m = re.search(
                                r"[ÜU]N\s*No\.?\s*\([^)]*\)\s*[ÜU]N\s*-?\s*(\d{3,4})\b",
                                sec14_text, re.IGNORECASE)
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
        # [\w/] → "ADR/RID/ADN Sınıfı" gibi eğik çizgili mod listelerini de
        # kapsar (\w tek başına "/" karakterini atlıyordu, bu format kaçıyordu).
        if sinif is None:
            m = re.search(
                r"\bADR[\w/]*\s*S[ıi]N[ıi]F\w*.{0,30}?\b(\d+(?:\.\d+)?)\b",
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
            # "Taşımacılık zararlılık sınıf(lar)ı:\n4.2" formatı —
            # etiket satırı, değer alt satırda tek başına (tire/boşuksuz).
            m = re.search(
                r"Ta[şsĢģ][ıi]mac[ıi]l[ıi][kğĞ]\s+zararlılık\s+s[ıi]n[ıi]f[^\n]*\n\s*(\d+(?:\.\d+)?)\b",
                sec14_text, re.IGNORECASE)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # BASF formatı: "Taşımacılık zararlılık 4.2\nsınıf(lar)ı:" —
            # değer etiketle aynı satırda, ama "sınıf(lar)ı:" kısmı alt satıra
            # taşmış. Değer ilk satırın sonunda bulunur.
            m = re.search(
                r"Ta[şsĢģ][ıi]mac[ıi]l[ıi][kğĞ]\s+zararlılık\s+(\d+(?:\.\d+)?)\s*\n\s*s[ıi]n[ıi]f",
                sec14_text, re.IGNORECASE)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # "Sınıfı\n:\n2" formatı — etiket, ":" ve değer 3 AYRI satırda
            # (14.1. ADR: alt başlığı, "UN Numarası" ile aynı tablo
            # yapısı). Sadece diğer tüm yöntemler başarısız olduğunda
            # devreye giriyor; _gecerli_sinif() ile 1-9 aralığı dışındaki
            # (örn. başka bir alanın değeri) yanlış eşleşmeler eleniyor.
            m = re.search(
                r"\bS[ıi]n[ıi]f[ıi]\s*\n\s*:?\s*\n?\s*(\d+(?:\.\d+)?)\b",
                sec14_text, re.IGNORECASE)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # "SINIF    5.1    5.1    ..." tablo formatı — satır başında
            # büyük harfle "SINIF" etiketi, ardından boşluklar ve değer
            # (örn. AK-KİM çok modlu tablo şablonu).
            m = re.search(
                r"(?im)^\s*S[Iİıi]N[Iİıi]F\s+(\d+(?:\.\d+)?)\b",
                sec14_text)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
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
        if sinif is None:
            # "Taşımacılık Sınıfı: 8" veya "Transport Class: 8" etiketi
            # (örn. Setacid/DyStar birleşik format — her mod için ayrı
            # satırda tekrar eden etiket).
            m = re.search(
                r"(?im)^\s*Ta[şsĢģ][ıi]mac[ıi]l[ıi][kğĞ]\s*S[ıi]n[ıi]f[ıi]\s*:\s*(\d+(?:\.\d+)?)\b",
                sec14_text)
            if not m:
                m = re.search(
                    r"(?im)^\s*Transport\s+(?:Hazard\s+)?Class\s*:\s*(\d+(?:\.\d+)?)\b",
                    sec14_text, re.IGNORECASE)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # TEKKİM tarzı şablon: etiket ve değer AYNI SATIRDA ama İKİ
            # NOKTA YOK, aralarında yalnızca boşluk var:
            #     "Sınıfı  5.1"      "Ambalaj grubu  III"
            # Yukarıdaki 1506 numaralı desen ":" ZORUNLU tuttuğu, 1481
            # numaralı desen ise "SINIF" ten sonra doğrudan boşluk beklediği
            # ("Sınıfı" daki sondaki "ı" yüzünden eşleşmiyor) için bu format
            # tüm zincirden kaçıyor ve sınıf okunamıyordu.
            # Değerin AYNI SATIRDA olması şartı, AK-KİM tablolarında satır
            # başında tek başına duran "SINIFI" kelimesiyle yanlış
            # eşleşmeyi önler (orada aynı satırda sayı yoktur).
            m = re.search(
                r"(?im)^\s*S[ıiİI]n[ıiİI]f[ıi]?\s+(\d+(?:\.\d+)?)\b",
                sec14_text)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # "14.3 Nakliyat tehlike sınf(lar)ı\nADR/RID: 8" formatı —
            # 14.3 başlığı var, değer hemen altında "ADR/RID: 8" şeklinde.
            # "sınf" (ı düşmüş) font bozulması da tolere edilir.
            m = re.search(
                r"14\s*\.?\s*3\b[^\n]*\n\s*ADR[/\w]*\s*:\s*(\d+(?:\.\d+)?)\b",
                sec14_text, re.IGNORECASE)
            if m and _gecerli_sinif(m.group(1), un_no):
                sinif = m.group(1)
        if sinif is None:
            # "UN 1760 AŞINDIRICI SIVI, B.B.B., 8, III" gibi P.G. olmadan
            # sadece virgülle ayrılmış sınıf ve PG içeren satır içi format.
            # UN no içeren satırı izole edip son iki virgüllü token'ı alıyoruz.
            m = re.search(
                rf"(?m)^[^\n]*\b[ÜU]N\s+{re.escape(str(un_no))}\b[^\n]*$",
                sec14_text, re.IGNORECASE)
            if m:
                satir = m.group(0)
                # Son iki virgülle ayrılmış kısım: "..., sınıf, PG"
                parcalar = [p.strip() for p in satir.split(',')]
                if len(parcalar) >= 2:
                    aday = parcalar[-2].strip()  # PG'den önceki = sınıf
                    if _gecerli_sinif(aday, un_no):
                        sinif = aday
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
            else:
                # "Ambalajlama Grubu: III" veya "Packing Group: III" etiketi
                # (örn. Setacid/DyStar birleşik format — her mod için ayrı satırda).
                m = re.search(
                    r"(?im)^\s*Ambalajlama\s+Gru[bp][üu]\s*:\s*(I{1,3})\b",
                    sec14_text)
                if not m:
                    m = re.search(
                        r"(?im)^\s*Packing\s+Group\s*:\s*(I{1,3})\b",
                        sec14_text, re.IGNORECASE)
                if m:
                    pg = m.group(1)
                else:
                    # "PAKETLEME GRUBU    II    II    ..." tablo formatı
                    m = re.search(
                        r"(?im)^\s*PAKETLEME\s+GRUBU\s+(I{1,3})\b",
                        sec14_text)
                    if m:
                        pg = m.group(1)
                    else:
                        # "14.4 Ambalaj grubu\nADR/RID: III" formatı
                        m = re.search(
                            r"14\s*\.?\s*4\b[^\n]*\n\s*ADR[/\w]*\s*:\s*(I{1,3})\b",
                            sec14_text, re.IGNORECASE)
                        if m:
                            pg = m.group(1)
                        else:
                            # "Ambalaj gurubu:\nII" formatı — etiket+iki nokta,
                            # değer alt satırda tek başına (gurup/grup varyasyonu).
                            m = re.search(
                                r"Ambalaj\s+g[ur]{1,2}ubu\s*:?\s*\n\s*(I{1,3})\b",
                                sec14_text, re.IGNORECASE)
                            if m:
                                pg = m.group(1)
                            else:
                                # BASF formatı: "Ambalaj gurubu:   II" aynı satırda
                                m = re.search(
                                    r"Ambalaj\s+g[ur]{1,2}ubu\s*:\s*(I{1,3})\b",
                                    sec14_text, re.IGNORECASE)
                                if m:
                                    pg = m.group(1)
                                else:
                                    # "ADR / RID, IMDG,   III" — PG değeri mod listesiyle
                                    # aynı satırda, büyük boşluklu sütun (ERCA GROUP şablonu)
                                    m = re.search(
                                        r"ADR\s*/\s*RID[^:\n]*\s{2,}(I{1,3})\b",
                                        sec14_text, re.IGNORECASE)
                                    if m:
                                        pg = m.group(1)
                                    else:
                                        # TEKKİM tarzı: "Ambalaj grubu  III"
                                        # — etiket ve değer AYNI SATIRDA,
                                        # İKİ NOKTA YOK (sınıf için eklenen
                                        # desenle aynı şablon sorunu).
                                        m = re.search(
                                            r"(?im)^\s*Ambalaj\s+g[ur]{1,2}ubu\s+(I{1,3})\b",
                                            sec14_text)
                                        if m:
                                            pg = m.group(1)

    return {"un_no": un_no, "sinif": sinif, "paketleme_grubu": pg}


def extract_adr_info(pdf_path: str, ai_chain: list = None, ai_models: dict = None,
                      ai_keys: dict = None, ai_ollama_url: str = ""):
    """Tek bir PDF'ten ADR (Bölüm 14) bilgisini VE Versiyon 2'nin diğer
    sütunları (tedarikçi, fonksiyon, cas no, H kodları vb.) için Bölüm
    1/2/3'ten ek bilgiyi tek seferde çıkarır.

    ai_chain verilmezse davranış tamamen eskisiyle aynıdır (sadece regex).
    ai_chain doluysa, regex'in boş bıraktığı alanlar (tedarikçi, fonksiyon,
    cas no, H kodları, tehlikeli/tehlikesiz, tehlike etiketi, revize tarihi)
    için AI tamamlayıcı katman devreye girer — bkz. extract_full_info."""
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
    result.update(extract_full_info(pdf_path, text=text, ai_chain=ai_chain,
                                     ai_models=ai_models, ai_keys=ai_keys,
                                     ai_ollama_url=ai_ollama_url))

    sec14 = find_section14_text(text)
    if sec14 is None:
        # Bölüm 14 bile bulunamadıysa -> manuel kontrol gerekli
        return result

    # Layout dolgu boşluklarını temizle — aşağıdaki TÜM desenler mesafe
    # pencerelerine dayandığı için bu adım zorunlu (bkz. _sec14_normalize).
    sec14 = _sec14_normalize(sec14)

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
            else:
                # parse_adr_first_line ilk satırı tanıyamadı — blok satırları
                # "etiket\ndeğer" çiftleri şeklinde olabilir (BASF/Clariant tarzı).
                # Satırları çift çift okuyarak UN no, sınıf ve PG çıkaralım.
                block_text = "\n".join(block)
                import re as _re
                _un = _re.search(r"\bUN\s*[-]?\s*(\d{3,4})\b", block_text)
                _sinif = _re.search(
                    r"zararlılık\s+s[ıi]n[ıi]f[^\n]*\n\s*(\d+(?:\.\d+)?)\b",
                    block_text, _re.IGNORECASE)
                if not _sinif:
                    # BASF formatı: değer etiketle aynı satırda, "sınıf(lar)ı:" alt satırda
                    _sinif = _re.search(
                        r"zararlılık\s+(\d+(?:\.\d+)?)\s*\n\s*s[ıi]n[ıi]f",
                        block_text, _re.IGNORECASE)
                _pg = _re.search(
                    r"(?:Ambalaj\s+g[ur]{1,2}ubu|Packing\s+[Gg]roup)[^\n]*\n\s*(I{1,3})\b",
                    block_text, _re.IGNORECASE)
                if not _pg:
                    # BASF formatı: "Ambalaj gurubu:   II" aynı satırda
                    _pg = _re.search(
                        r"Ambalaj\s+g[ur]{1,2}ubu\s*:\s*(I{1,3})\b",
                        block_text, _re.IGNORECASE)
                if _un:
                    result["adr_kapsaminda"] = True
                    result["un_no"] = _un.group(1)
                    result["sinif"] = _sinif.group(1) if _sinif else None
                    result["paketleme_grubu"] = _pg.group(1) if _pg else None
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

