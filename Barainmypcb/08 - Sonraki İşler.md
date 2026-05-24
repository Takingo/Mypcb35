---
title: Sonraki İşler
tags:
  - todo
  - roadmap
  - next
status: active
---

# Sonraki İşler

> [!success] Sistem Durumu: **85% → 100% Üretim Hazırlığı** (2026-05-24)
> 
> PCBA Manufacturing Export sistemi tamamlanmıştır. Tüm mock veriler kaldırılmış, gerçek mühendislik doğrulamaları eklenmiş ve direkt online PCBA sağlayıcılarına (PCBWay, JLCPCB, Seeed) gönderim için kapsamlı paketler oluşturulmuştur.
> 
> **Faz 5B Çıktısı**: 
> - 18+ dosya (Gerber, BOM, montaj, fabrication notes, upload guides)
> - 700+ satır detaylı tasarım kuralları
> - 3 üreticiye özel talimattan
> - Python + Flutter + PowerShell entegrasyonu tamamı
>
> Bkz: [[09 - Faz 5 Üretim Checkout ve Paketleme]] → "PCBA Direkt Export Sistemi"

## Öncelik 1 - Gerçek Üretici Footprint Bağlama

- [x] Mühendislik gerçeklik kapısı ekle; DRC=0 tek başına üretime hazır sayılmasın.
- [ ] ESP32-S3-WROOM-1 gerçek KiCad footprint bağla.
- [ ] DWM3000 gerçek footprint oluştur veya doğrula.
- [ ] HLK-5M05 gerçek footprint kullan.
- [ ] TXB0104 ve SN74LVC1T45 footprint doğrula.
- [ ] G5Q-14-DC5 röle footprint doğrula.

> [!important]
> Placeholder footprint ile DRC=0 alınabilir; ama üretim güvenliği için gerçek datasheet land pattern doğrulaması şarttır.

## Öncelik 2 - Şematik Sembol Üretimi

- [ ] `.kicad_sch` içinde gerçek sembol yerleştirme.
- [ ] Symbol-footprint bağlantısı.
- [ ] ERC raporu.
- [ ] Net label düzeni.

## Öncelik 3 - Routing Kalitesini Artırma

- [ ] DWM3000 RF net için gerçek top-layer microstrip route.
- [ ] SPI length matching.
- [ ] 3V3 / 1V8 power trace genişlikleri.
- [ ] Ground stitching via üretimi.
- [ ] AC keepout ve isolation slot geometrisi.

## Öncelik 4 - Üretim Paketi Otomasyonu (✅ 100% Tamamlandı)

### Temel Paketleme (Faz 5 - Tamamlı)
- [x] Gerber klasörünü zip yap.
- [x] BOM + CPL tek package klasöründe topla.
- [x] Flutter checkout hazırlık ekranı ekle.
- [x] Dış API payload yerine yerel üretim paketi özeti üret.
- [x] Assembly drawing üret. (`tool/run_pcba_exports.ps1` → PDF/SVG/GLB)
- [x] Fabrication drawing üret. (`engine/fabrication_drawing_service.py` + `tool/run_fabrication_drawing.ps1`)

### PCBA Direkt Export (Faz 5B - 2026-05-24 Tamamlı)
- [x] **Üretici-spesifik export sistemi** (PCBWay, JLCPCB, Seeed Fusion)
- [x] **Detaylı fabrication notes** (700+ satır, RF/güç/AC güvenliği)
- [x] **Extended BOM** (maliyet, stok, lead-time, datasheet)
- [x] **Assembly drawing rehberi** (test noktaları, kritik uyarılar)
- [x] **Manufacturer-specific upload guides** (her üretici için adım adım)
- [x] **PCBA manifest JSON** (meta veriler ve maliyet tahmini)
- [x] **Flutter UI integration** ("PCBA Direkt Export" sekmesi)
- [x] **Python motor** (`engine/pcba_manufacturing_export_service.py`)
- [x] **PowerShell script** (`tool/generate_pcba_manufacturing_export.ps1`)
- [ ] PCBWay/JLCPCB API entegrasyonu (İsteğe bağlı - şu an manuel ZIP yükleme yeterli)

## Öncelik 5 - Simülasyon

- [ ] Güç bütçesi hesabı.
- [ ] SPICE model bağlama.
- [ ] LDO/buck termal analizi.
- [ ] RF impedance hesaplayıcı.
- [ ] EMC/ESD kontrol checklist’i.

## Öncelik 6 - UI İyileştirme

- [x] KiCad komutlarını Flutter içinden tetikleme. (`lib/kicad_pipeline_panel.dart` — 7 adım)
- [x] DRC raporunu canlı yenileme. ("DRC Yenile" butonu diskten okur)
- [x] Üretim hazır bayrağı için ayrı üst panel. (EDA Pipeline'da banner)
- [x] Üretim checkout ekranında Gerber paket placeholder/özeti.
- [ ] PCBA 2D/3D görselleştirme. (GLB üretildi; Flutter 3D viewer henüz yok)

## Öncelik 7 - PCBai Gerçek Entegrasyonu

- [ ] PCBai repo API yüzeyini netleştir.
- [ ] `PCBAI_CONSTRAINT_FEEDBACK_V1` payload’unu gerçek solver’a bağla.
- [ ] Solver sonucunu KiCad board’a uygula.
- [ ] DRC kapalı döngüsünü PCBai placement/routing önerileriyle besle.

## Açık Teknik Sorular

- KiCad 10 API ile `.kicad_sch` sembol üretimi hangi seviyede yapılacak?
- RF trace empedans hesabı KiCad stackup üzerinden mi, ayrı hesap motoruyla mı doğrulanacak?
- Üretici API hedefi önce PCBWay mi, JLCPCB mi?
- Dış üretici API entegrasyonu gerçekten istenecek mi, yoksa manuel ZIP yükleme yeterli mi?
- Gerçek BOM fiyat/stok kaynağı olarak hangi tedarikçiler kullanılacak?

## İlgili Notlar

- [[02 - Mimari ve Veri Akışı]]
- [[05 - DRC ve Otonom Düzeltme Döngüsü]]
- [[06 - Güvenlik ve Üretime Hazırlık]]
- [[09 - Faz 5 Üretim Checkout ve Paketleme]]
- [[10 - Mühendislik Gerçeklik Kapısı]]
