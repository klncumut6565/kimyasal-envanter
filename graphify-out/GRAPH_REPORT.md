# Graph Report - kimyasal-envanter  (2026-11-16)

## Corpus Check
- 16 files · ~253,531 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 3 file(s) not represented in the graph (top: (none) 1, .toml 1, .patch 1)

## Summary
- 332 nodes · 650 edges · 28 communities (18 shown, 10 thin omitted)
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `62e17abc`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- app.py
- ai_destek.py
- extract_adr_info
- extract_full_info
- extractor.py
- re
- add_products
- excel_writer.py
- _extract_fonksiyon
- fill_or_append_v2
- extract_cas_listesi
- extract_revize_tarihi
- Kimyasal Envanter Oluşturucu
- etiket_gorselleri.py
- add_products_v3
- _norm
- pdf_to_text
- create_new_envanter
- fonksiyon_turkcelestir
- _auto_fit_row_height
- create_new_sentez_envanter
- _tedarikci_temizle
- data/README.md
- ADR_A_TABLOSU_907441e9.md
- BOS_ENVANTER_SABLONU_6fa30cd6.md
- BOS_ENVANTER_SABLONU_V3_0582c159.md

## God Nodes (most connected - your core abstractions)
1. `add_products()` - 20 edges
2. `extract_adr_info()` - 20 edges
3. `extract_full_info()` - 19 edges
4. `build_inventory_row()` - 15 edges
5. `find_section_text()` - 13 edges
6. `render_export_ui()` - 12 edges
7. `fill_or_append_v2()` - 11 edges
8. `_call_openai_compatible()` - 10 edges
9. `json_ayikla()` - 9 edges
10. `tamamla_eksik_alanlar()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `existing_names()` --calls--> `find_column()`  [EXTRACTED]
  app.py → excel_writer.py
- `fonksiyon_turkcelestir()` --calls--> `fonksiyon_cevir()`  [EXTRACTED]
  extractor.py → ai_destek.py
- `extract_full_info()` --calls--> `tamamla_eksik_alanlar()`  [EXTRACTED]
  extractor.py → ai_destek.py
- `render_export_ui()` --calls--> `add_products()`  [EXTRACTED]
  app.py → excel_writer.py
- `render_export_ui()` --calls--> `add_products_v3()`  [EXTRACTED]
  app.py → excel_writer.py

## Import Cycles
- None detected.

## Communities (28 total, 10 thin omitted)

### Community 0 - "app.py"
Cohesion: 0.05
Nodes (27): atik_kodlari_eslestir(), existing_names(), _grup_ciz(), _manuel_mi(), _oncelik(), render_export_ui(), _satir_durumu(), save_upload() (+19 more)

### Community 1 - "ai_destek.py"
Cohesion: 0.06
Nodes (28): _cache_path(), cache_stats(), cached_call(), clear_cache(), _hash_of(), build_failover_chain(), _build_tamamlama_prompt(), _call_ai() (+20 more)

### Community 2 - "extract_adr_info"
Cohesion: 0.10
Nodes (14): _alt_bolum_penceresi(), _eksik_alanlari_tamamla(), _etiketli_tasima_bilgisi(), extract_adr_info(), find_adr_block(), _gecerli_sinif_degeri(), _is_section_label(), parse_adr_first_line() (+6 more)

### Community 3 - "extract_full_info"
Cohesion: 0.14
Nodes (9): _esnek_desen(), extract_full_info(), extract_h_kodlari(), extract_kimyasalin_turu(), extract_msds_dili(), extract_tehlikeli_tehlikesiz(), extract_uretici(), extract_urun_kodu() (+1 more)

### Community 4 - "extractor.py"
Cohesion: 0.18
Nodes (9): _adr_konumu(), extract_tedarikci(), _extract_tedarikci(), extract_uyari_kelimesi(), _extract_uyari_kelimesi(), _pipe_ilk_hucre(), _pipe_satir_deger(), _tedarikci_aday() (+1 more)

### Community 5 - "re"
Cohesion: 0.19
Nodes (7): _ad_sorunu(), explicit_not_in_scope(), extract_suggested_name(), find_section14_text(), kesin_kapsam_disi(), _urun_adi_gecersiz(), _urun_adi_kirp()

### Community 6 - "add_products"
Cohesion: 0.15
Nodes (7): adr_etiket_kodlari(), add_products(), _embed_qr_code(), _etiket_gorseli_goml(), _find_footer_row(), _find_last_data_row(), _shift_rows_down()

### Community 7 - "excel_writer.py"
Cohesion: 0.21
Nodes (3): _find_existing_row_by_name(), _normalize_name(), clean_product_name()

### Community 8 - "_extract_fonksiyon"
Cohesion: 0.18
Nodes (6): extract_fonksiyon(), _extract_fonksiyon(), extract_fonksiyon_ham(), _fonksiyon_gecersiz(), _fonksiyon_kisalt(), _fonksiyon_temizle()

### Community 9 - "fill_or_append_v2"
Cohesion: 0.22
Nodes (5): _add_pdf_hyperlink(), _copy_row_style(), fill_or_append_v2(), _satirda_gercek_un_no_var_mi(), _strip_bold()

### Community 10 - "extract_cas_listesi"
Cohesion: 0.22
Nodes (5): _cas_check_digit(), _cas_normalize(), extract_cas_listesi(), _ekle(), extract_cas_no()

### Community 11 - "extract_revize_tarihi"
Cohesion: 0.22
Nodes (4): extract_revize_tarihi(), _extract_revize_tarihi(), _issue_date_referansli(), normalize_tarih()

### Community 12 - "Kimyasal Envanter Oluşturucu"
Cohesion: 0.22
Nodes (8): 1) GitHub Reposu Hazırlama, 2) Streamlit Community Cloud'da Deploy, Bilinen Sınırlamalar, Kimyasal Envanter Oluşturucu, Nasıl Çalışır?, Streamlit Cloud'a Dağıtım (Adım Adım), Yerel Çalıştırma, Özel Durumlar

### Community 14 - "add_products_v3"
Cohesion: 0.25
Nodes (4): add_products_v3(), _v3_bos_otomatik_sutunlari_gizle(), _v3_data_style(), _v3_manuel_sutunlari_hep_gizle()

### Community 15 - "_norm"
Cohesion: 0.32
Nodes (4): build_column_map(), ensure_note_header(), find_column(), _norm()

### Community 16 - "pdf_to_text"
Cohesion: 0.29
Nodes (3): _metin_bozuk_mu(), _ocr_sayfa(), pdf_to_text()

### Community 17 - "create_new_envanter"
Cohesion: 0.33
Nodes (3): create_new_envanter(), _set_value_right_of_label(), _title_cell()

### Community 18 - "fonksiyon_turkcelestir"
Cohesion: 0.33
Nodes (3): fonksiyon_turkcelestir(), _ingilizce_mi(), _sozlukten_cevir()

## Knowledge Gaps
- **10 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `extract_adr_info()` connect `extract_adr_info` to `app.py`, `extract_full_info`, `extractor.py`, `re`, `excel_writer.py`, `extract_revize_tarihi`, `pdf_to_text`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Should `app.py` be split into smaller, more focused modules?**
  _Cohesion score 0.053939714436805924 - nodes in this community are weakly interconnected._
- **Why does `add_products()` connect `add_products` to `app.py`, `re`, `excel_writer.py`, `fill_or_append_v2`, `_norm`, `create_new_envanter`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Should `ai_destek.py` be split into smaller, more focused modules?**
  _Cohesion score 0.062310949788263764 - nodes in this community are weakly interconnected._
- **Why does `build_inventory_row()` connect `app.py` to `re`, `excel_writer.py`?**
  _High betweenness centrality (0.024) - this node is a cross-community bridge._
- **Should `extract_adr_info` be split into smaller, more focused modules?**
  _Cohesion score 0.10461538461538461 - nodes in this community are weakly interconnected._
- **Should `extract_full_info` be split into smaller, more focused modules?**
  _Cohesion score 0.1437908496732026 - nodes in this community are weakly interconnected._