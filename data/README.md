# data/ dizini

Bu klasörde iki referans dosyası bulunmalıdır:

| Dosya | Açıklama |
|---|---|
| `ADR_A_TABLOSU.xlsx` | Resmi ADR Tablo A referans dosyası. Güncellendiğinde bu dosyayı değiştirin — kod değişmez. |
| `BOS_ENVANTER_SABLONU.xlsx` | Yeni envanter oluşturmak için kullanılan boş şablon dosyası (başlık, imza bloğu, sütun formatları içerir). |

**Önemli:** Bu iki dosya `data/` klasöründe yoksa uygulama "Yeni envanter oluştur" ve Tablo A eşleştirme özelliklerini kullanamaz.  
Dosyalar GitHub reposuna `.gitignore`'a eklenmeden **commite dahil edilmelidir**.
