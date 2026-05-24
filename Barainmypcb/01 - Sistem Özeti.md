---
title: Sistem Özeti
tags:
  - omnicircuit
  - overview
  - eda
status: active
---

# Sistem Özeti

**OmniCircuit AI**, ham elektronik isterlerden üretime yaklaşan PCB/PCBA dosyalarına giden otonom bir EDA hattı olarak geliştirilmektedir.

Sistem şu ana fikir üzerine kuruludur:

> Kullanıcı BOM veya teknik ihtiyaç verir. Sistem eksik yardımcı devreleri tamamlar, netlist üretir, KiCad üzerinden şematik/PCB taslağı oluşturur, DRC çalıştırır, DRC hatalarını ayrıştırır, otomatik düzeltir ve DRC=0 olduğunda üretim dosyalarını export eder.

## İlk Örnek Devre

ESP32-S3 + DWM3000 UWB anchor:

- ESP32-S3 3.3V MCU
- DWM3000 1.8V UWB modül
- 220V AC giriş
- HLK-5M05 izole 5V güç kaynağı
- TPS54331 3.3V buck
- TPS7A2018PDBVR 1.8V low-noise LDO
- TXB0104 SPI level shifter
- SN74LVC1T45 RTLS pin level shifter
- PC817 + 2N7002 ile röle sürücü izolasyonu

## Sistem Ne Yapıyor?

- BOM ve teknik girdiyi okur.
- Voltaj domain farklarını yakalar.
- Eksik level shifter, regülatör, koruma ve röle sürücü elemanlarını ekler.
- `AI_Netlist_v1` üretir.
- KiCad `.kicad_pro`, `.kicad_sch`, `.kicad_pcb` dosyaları oluşturur.
- DWM3000 için 1.0mm pitch kuralını uygular.
- RF net için 50 ohm / top layer / viasız hard constraint yaklaşımını korur.
- AC bölgesi için 8mm izolasyon kuralını uygular.
- KiCad DRC raporunu `DRC_REPORT_V1` formatına dönüştürür.
- Clearance ve silkscreen gibi hataları otomatik düzeltir.
- DRC=0 olduğunda Gerber, drill ve position dosyalarını üretir.
- Üretim dosyalarını `Quantum_Mind_Anchor_v2_4_Production.zip` paketinde toplar.
- Flutter içinde üretim checkout hazırlık ekranı gösterir.

## Sistem Ne Değil?

> [!warning]
> Bu sistem henüz bütün elektronik komponentlerin gerçek üretici footprint doğrulamasını, SPICE model bağlamayı, RF saha simülasyonunu ve tedarikçi DFM onayını tam otomatik garanti eden nihai bir ürün değildir.

Kritik üretim öncesi insan incelemesi gereken alanlar:

- AC şebeke güvenliği
- RF empedans doğrulaması
- Gerçek footprint / land pattern uyumu
- Termal tasarım
- Üretici kuralları
- EMC/EMI değerlendirmesi

## Ana Modüller

- Flutter dashboard: kullanıcı arayüzü
- `cognitive_netlist_generator.py`: bilişsel netlist motoru
- `kicad_automation_service.py`: KiCad proje ve export köprüsü
- `drc_parser.py`: DRC rapor ayrıştırıcı
- `pcbai_feedback_adapter.py`: PCBai penalty payload hazırlayıcı
- `layout_optimizer_service.py`: kapalı döngü layout düzeltici
- `fabrication_api_service.py`: yerel üretim ZIP paketi ve checkout özeti hazırlayıcı
- `manufacturing_dashboard.dart`: üretim ve sipariş hazırlığı ekranı

Detaylı akış için bkz. [[02 - Mimari ve Veri Akışı]].
