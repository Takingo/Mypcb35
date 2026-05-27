---
title: Sistem Ozeti
tags:
  - omnicircuit
  - overview
  - eda
status: active
updated: 2026-05-26
---

# Sistem Ozeti

**OmniCircuit AI**, ham elektronik isterlerden KiCad tabanli PCB/PCBA uretim adayina giden bir EDA otomasyon hattidir. Sistem gelistirme asamasindadir; guncel durumda fiziksel uretime hazir degildir.

> [!success] Guncel Gercek
> Son dogrulanmis regenerate DRC total `0`: 0 error, 0 unconnected, 0 dangling. Engineering readiness `review_required` ve `%89` (8/9, 0 bloklayici). Fabrication ZIP `package_ready` uretiliyor. Tek kalan kapi: `REAL_SIMULATION` muhendis incelemesi (RF/AC/thermal/datasheet). Fiziksel uretim oncesi engineering review + uretici DFM gerekir.

## Ilk Ornek Devre

ESP32-S3 + DWM3000 UWB anchor:

- ESP32-S3 3.3V MCU
- DWM3000 1.8V UWB modul
- 220V AC giris
- HLK-5M05 izole 5V guc kaynagi
- TPS54331 3.3V buck
- TPS7A2018PDBVR 1.8V low-noise LDO
- TXB0104 SPI level shifter
- SN74LVC1T45 RTLS pin level shifter
- PC817 + 2N7002 ile role surucu izolasyonu

## Sistem Ne Yapiyor?

- BOM ve teknik girdiyi okur.
- Eksik yardimci devreleri ve domain gereksinimlerini netliste tasir.
- `AI_Netlist_v1` uretir.
- KiCad `.kicad_pro`, `.kicad_sch`, `.kicad_pcb` dosyalari olusturur.
- KiCad ERC ve DRC calistirir.
- DRC raporunu Flutter ve Python servislerinin okuyacagi asset/JSON formatina aktarir.
- Layout optimizer ile deterministik iyilestirme dener.
- Optimizer kotu sonuc uretirse rollback yapar.
- DRC ve production model gate gecmeden uretim ZIP'i uretmez.

## Sistem Su Anda Ne Yapmiyor?

- U2 DWM3000 icin resmi/dogrulanmis uretici footprint'i kullanmiyor (sentetik footprint).
- RF stackup, AC creepage/clearance ve SPICE/thermal dogrulamasini otomatik gecmiyor; muhendis incelemesi (`REAL_SIMULATION` review) bekliyor.
- "%100 calisir/uretilir" garantisi vermiyor; fiziksel uretim icin uretici DFM ve prototip gerekir.

## Sistem Artik Ne Yapiyor? (2026-05-26)

- DRC=0 uretiyor (0 error, 0 unconnected, 0 dangling) — gercek `kicad-cli` ile dogrulandi.
- Aktif AI netlist dolu/izlenebilir `components` ve `nets` kaniti tasiyor.
- `_prune_dangling_copper` ile zone fill sonrasi bos via/track'leri temizliyor.
- Fabrication ZIP paketini (`package_ready`) gercek kapilar gecince uretiyor.

## Uretim Icin Gerekli Kosul

```text
KiCad DRC=0
manufacturing_ready=true
design_source_evidence=pass
production_model_gate=pass
engineering_readiness=production_candidate
```

## Ana Moduller

- Flutter dashboard: kullanici arayuzu
- `engine/cognitive_netlist_generator.py`: netlist motoru
- `engine/design_evidence_gate.py`: AI netlist/BOM elektriksel kaynak kaniti kapisi
- `engine/kicad_automation_service.py`: KiCad proje ve DRC koprusu
- `engine/layout_optimizer_service.py`: kapali dongu layout duzeltici
- `engine/production_model_gate.py`: footprint ve pad-net uretim modeli kapisi
- `engine/engineering_readiness_service.py`: muhendislik hazirlik denetimi
- `engine/fabrication_api_service.py`: gate gecerse yerel uretim ZIP paketi

Detayli akis icin bkz. [[02 - Mimari ve Veri Akışı]].
