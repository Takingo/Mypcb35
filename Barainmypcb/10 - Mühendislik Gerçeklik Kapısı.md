---
title: Muhendislik Gerceklik Kapisi
tags:
  - omnicircuit
  - engineering-readiness
  - kicad
  - safety-gate
status: active
updated: 2026-05-26
---

# Muhendislik Gerceklik Kapisi

Bu kapinin gorevi sistemin kendini oldugundan daha hazir gostermesini engellemektir. Proje ancak gercek KiCad kanitlari, izlenebilir kaynak modeli ve uretim kontrolleri gecerse `production_candidate` olabilir.

> [!success] Son Karar
> Mühendis sign-off kaydedildiginde durum `production_candidate` (**%100, 9/9, 0 bloklayici, 0 review**). Sign-off yoksa `review_required` (%89, 8/9) — `REAL_SIMULATION` insan onayi bekler. Sistem sign-off'u ASLA kendisi uydurmaz. Fiziksel uretim icin yine uretici DFM + prototip onerilir.

## Son Denetim

Kaynak:

```text
outputs/engineering/engineering_readiness_report.json
outputs/engineering/manual_signoff.json   (mühendis imzasi — varsa REAL_SIMULATION pass)
outputs/simulation/simulation_report.json (5 otomatik kontrol)
```

Son sonuc (sign-off kaydedildikten sonra):

```text
overall_status: production_candidate
readiness_percent: 100
passed_checks: 9/9
blocker: 0
review_warning: 0
```

Sign-off OLMADAN: `review_required`, %89, 8/9, 1 review (REAL_SIMULATION).

## Gecen Kontroller (9/9 — sign-off ile)

- `BOM_SOURCE`: BOM kritik komponentleri iceriyor.
- `DESIGN_SOURCE_EVIDENCE`: AI netlist komponent/net/BOM izlenebilirlik kapisini gecti.
- `SCHEMATIC_SYMBOLS`: Sematik gercek KiCad symbol instance iceriyor ve ERC temiz.
- `PCB_ARTIFACT`: Aktif PCB footprint verisi iceriyor; stub degil.
- `PRODUCTION_MODEL`: Footprint kimlikleri ve pad-net modeli uretim kapisini gecti.
- `DRC_EVIDENCE`: KiCad DRC total 0 (0 error, 0 unconnected, 0 dangling). **Pass.**
- `PCBA_HANDOFF`: DRC temiz. **Pass.**
- `FAB_ZIP`: DRC temiz, paket `package_ready`. **Pass.**
- `REAL_SIMULATION`: 5 otomatik kontrol (Power Budget, RF Impedance, Thermal, Decoupling Coverage, AC Safety) + mühendis sign-off. **Pass (sign-off ile).**

## Cozulen Bloklayicilar (2026-05-26)

### DRC_EVIDENCE — Cozuldu

```text
Onceki: total=20, 20 via_dangling, manufacturing_ready=false
Simdi:  total=0,  0 dangling, 0 unconnected, manufacturing_ready=true
```

Cozum: `engine/kicad_automation_service.py::_prune_dangling_copper` — zone fill sonrasi
reloaded board uzerinde <2 bakir katmanina bagli via'lari ve bos uclu track'leri
(T-junction farkindalikli, unconnected uretmeden) iteratif siler.

Kalan tasarim aksiyonu (review sinifi):

- DWM3000 icin sentetik footprint yerine uretici/kurumsal footprint kaniti ekle.

## REAL_SIMULATION Mekanizmasi (2026-05-26)

`engine/simulation_service.py` 5 otomatik ilk-derece kontrol uretir:

```text
Power Budget        -> pass  (BOM akim butcesi, ray bazinda)
RF Microstrip Imp.  -> pass  (Hammerstad 50ohm tahmini)
Thermal Estimate    -> pass  (junction sicaklik ilk-derece)
Decoupling Coverage -> pass  (gercek board: kondansator/IC orani)
AC Safety + Reality -> pass/review  (mühendis sign-off'a bagli)
```

Otomatik DOGRULANAMAYAN 4 madde (datasheet pinout, RF stackup dielektrik, AC creepage
sertifikasyon, SPICE/SI/PI/thermal modelleri) ancak `outputs/engineering/manual_signoff.json`
ile GERCEK bir mühendis acikca imzalarsa `verified` sayilir. Sistem imzayi ASLA uydurmaz.

- Imza yok -> AC Safety `review` -> REAL_SIMULATION `warn` -> overall `review_required %89`.
- Tüm maddeler imzali -> AC Safety `pass` -> REAL_SIMULATION `pass` -> overall `production_candidate %100`.

Sign-off kaydetme:

```powershell
.\tool\run_engineering_signoff.ps1 -Engineer "Ad Soyad" -All -Notes "..."
.\tool\run_simulation_checks.ps1
.\tool\run_engineering_audit.ps1
```

> Durustluk: sign-off, bir mühendisin sorumlulugu kaydetmesidir; fiziksel %100 garanti DEGILDIR.
> Üretici DFM + prototip yine onerilir.

## Dogrulama Komutlari

```powershell
.\tool\verify_board.ps1
.\tool\run_kicad_phase2.ps1 -Export
.\tool\run_simulation_checks.ps1
.\tool\run_engineering_signoff.ps1 -Engineer "Ad Soyad" -All
.\tool\run_engineering_audit.ps1
.\tool\run_fabrication_package.ps1
```

Beklenen son davranis:

- DRC temiz degilken `run_engineering_audit.ps1` raporu `blocked` yazar.
- DRC/source evidence temiz degilken `run_fabrication_package.ps1` hata ile durur; bu dogru davranistir.

## Kapi Kurali

Uretim kapisi yalnizca su durumda acilir:

```text
design_source_evidence=pass          [OK]
DRC=0                                 [OK]
unconnected_items=0                   [OK]
via_dangling=0                        [OK]
manufacturing_ready=true              [OK]
production_model_gate=pass            [OK]
engineering_readiness=production_candidate   [OK — mühendis sign-off kaydedildi]
```

Tüm kapilar gecti. `engineering_readiness=production_candidate %100`; `REAL_SIMULATION`
otomatik kontrolleri + mühendis sign-off ile gecti. Bu, otomasyonun + kayitli mühendis
sorumlulugunun tavanidir; fiziksel uretim icin uretici DFM + prototip yine sarttir.
