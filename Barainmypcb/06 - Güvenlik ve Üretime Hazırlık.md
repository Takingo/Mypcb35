---
title: Guvenlik ve Uretime Hazirlik
tags:
  - safety
  - manufacturing
  - review
status: active
updated: 2026-05-26
---

# Guvenlik ve Uretime Hazirlik

Bu not, uretim oncesi kilitleri acik ve durust tutmak icin yazilmistir.

> [!warning] Nihai Uretim Uyarisi
> Otomasyon kapilari temiz: DRC total `0`, readiness `%89`, engineering audit `review_required` (0 bloklayici). Fiziksel uretim oncesi `REAL_SIMULATION` muhendis incelemesi (RF/AC/thermal/datasheet) ve uretici DFM zorunludur.

## Guncel Kontrol Listesi

- [x] KiCad 10.0.3 bridge calisiyor.
- [x] KiCad ERC temiz raporlaniyor.
- [x] Aktif PCB dosyasi footprint verisi iceriyor.
- [x] Design source evidence gate eklendi.
- [x] Production model gate eklendi.
- [x] Fabrication ZIP DRC temiz degilse duruyor.
- [x] Aktif AI netlist dolu `components` ve `nets` kanitiyla yeniden uretildi.
- [x] KiCad DRC=0 dogrulandi (0 error, 0 unconnected, 0 dangling).
- [x] `manufacturing_ready=true` dogrulandi.
- [ ] U2 DWM3000 resmi/dogrulanmis footprint ile degistirildi.
- [ ] U2/U3/U7 no-net padleri bilincli NC veya gercek net olarak modellendi.
- [ ] UWB RF trace uretici stackup ile 50 ohm dogrulandi.
- [ ] AC primer ve dusuk voltaj tarafi creepage/clearance sertifikasyonla dogrulandi.
- [ ] Regulator akim/isi hesabi gercek SPICE/SI/PI/thermal modelle dogrulandi.
- [ ] BOM uretici parca numaralari ve stok durumu dogrulandi.
- [ ] Uretici DFM kontrolu yapildi.

## Uretim Icin Gerekli Dosyalar

Bu dosyalar ancak gate gecerse uretime kanit sayilir:

```text
outputs/phase4/gerber/
outputs/phase4/drill/
outputs/phase4/position/pick_and_place.csv
outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip
```

Guncel durumda eski/onceki kosulardan kalmis dosyalar olabilir; son gate `blocked` oldugu icin bunlar uretim onayi degildir.

## Guvenli Export Mantigi

Sistem yalnizca su durumda uretim paketi cikarmalidir:

```text
final_violation_count == 0
manufacturing_ready == true
design_source_evidence == pass
production_model_gate == pass
engineering_readiness == production_candidate
```

Guncel durum:

```text
final_violation_count = 0
manufacturing_ready = true
design_source_evidence = pass
production_model_gate = pass
engineering_readiness = review_required (REAL_SIMULATION review bekliyor)
```

## Ureticiye Gonderme Kurali

PCBWay/JLCPCB/Seeed gibi bir ureticiye manuel yukleme ancak su kanitlarla yapilabilir:

- DRC=0 raporu
- ERC temiz raporu
- Production model gate pass
- BOM/CPL/Gerber/drill tutarliligi
- Assembly/fabrication drawing
- Datasheet pinout incelemesi
- RF stackup/impedance onayi
- AC guvenlik onayi

Bugunku durumda bu kosullar saglanmiyor.
