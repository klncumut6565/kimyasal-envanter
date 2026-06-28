# Kimyasal Envanter Oluşturucu

MSDS PDF'lerinin **Bölüm 14 (Taşıma Bilgileri)** kısmındaki ADR satırını okuyup,
**ADR Tablo A** ile tam eşleştirip, sonucu mevcut **Envanter Excel** dosyasına
otomatik satır olarak ekleyen araç.

## Streamlit Cloud'a Dağıtım (Adım Adım)

### 1) GitHub Reposu Hazırlama

Aşağıdaki klasör yapısıyla bir **GitHub reposu** oluşturun (veya var olanı güncelleyin):

```
kimyasal-envanter/          ← repo kök dizini
├── app.py
├── extractor.py
├── matcher.py
├── excel_writer.py
├── requirements.txt
├── .gitignore
├── .streamlit/
│   └── config.toml         ← Streamlit ayar dosyası (bu repoda mevcut)
└── data/
    ├── ADR_A_TABLOSU.xlsx       ← SİZ EKLEYİN (repoya commit edin)
    └── BOS_ENVANTER_SABLONU.xlsx ← SİZ EKLEYİN (repoya commit edin)
```

> **Kritik:** `data/` klasörü içindeki iki xlsx dosyasını GitHub'a yüklemeyi
> unutmayın — bunlar `.gitignore`'da değil, repoda olmalı.

### 2) Streamlit Community Cloud'da Deploy

1. [share.streamlit.io](https://share.streamlit.io) adresine gidin
2. GitHub hesabınızla giriş yapın
3. **"New app"** → **"From existing repo"** seçin
4. Reponuzu ve `main` (veya `master`) dalını seçin
5. **Main file path:** `app.py`
6. **"Deploy!"** butonuna tıklayın

Deployment genellikle 2–4 dakika sürer.

---

## Nasıl Çalışır?

1. Sol menüden iki moddan birini seçin:
   - **🆕 Yeni envanter oluştur**: Sadece **Firma Adı**'nı yazın, isterseniz
     **Firma Logosu** yükleyin.
   - **📂 Var olan envanter çıktısını güncelle**: Daha önce oluşturduğunuz
     envanter dosyasını yükleyin.
2. Bir veya birden çok **MSDS PDF** dosyası seçin (çoklu seçim desteklenir).
3. Her PDF için otomatik olarak:
   - Bölüm 14 içindeki **"ADR"** satırı bulunur (UN No, Sınıf, Paketleme Grubu)
   - Tablo A'da satır aranır; eşleşirse tüm ayrıntılar otomatik doldurulur
   - "Revize Edildiği Tarih" otomatik okunup MSDS/SDS Tarihi alanına yazılır
4. **"Excel'e Aktar"** → güncellenen dosyayı indirin.

## Özel Durumlar

- **ADR kapsamında değil**: İlgili hücrelere otomatik metin yazılır.
- **Manuel kontrol gerekli**: Bölüm 14 okunamazsa ilgili hücreler işaretlenir.

## Yerel Çalıştırma

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Bilinen Sınırlamalar

- **Yeni envanter oluşturulduğunda**: "Doküman No" ve "Revizyon Tarihi" alanları
  elle doldurulmalıdır (firmaya özel).
- **ADR Tablo A güncellemesi**: `data/ADR_A_TABLOSU.xlsx` dosyasını yenisiyle
  değiştirin — kod değişmez.
- Bölüm 14 okuma kural tabanlı (regex) çalışmaktadır; çok farklı formatlı
  MSDS'lerle karşılaşılırsa manuel kontrol gerekebilir.
