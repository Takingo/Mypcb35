---
title: Sonraki Isler
tags:
  - roadmap
  - blockers
  - production
status: active
updated: 2026-05-26
---

# Sonraki Isler

> [!success] Sistem Durumu
> Otomasyon kapilari temiz: `review_required`, readiness `%89` (8/9), board manifest DRC total `0`, `manufacturing_ready=true`. 0 bloklayici. Fiziksel uretim oncesi tek kalan: `REAL_SIMULATION` muhendis incelemesi + DWM3000 footprint + uretici DFM.

## P0 - Once Gercegi Tekilleştir

- [x] `board_verification_manifest.json` ekle: netlist hash, PCB hash, KiCad version, DRC count, unconnected count.
- [x] `run_kicad_phase2.ps1` ve `engineering_readiness_report.json` board manifest ile beslensin.
- [ ] `verify_board.ps1` ve UI stale-status gostergesi manifest politikasina tamamen baglansin.
- [ ] Brainmypcb otomatik rapor yazici ekle; eski `331`, `6`, `26/25` gibi stale sayilar tekrar kalmasin.
- [ ] UI'da stale asset varsa "gecersiz/eski rapor" olarak goster.

## P0 - Source Evidence Gate

- [x] AI netlistte olmayan `K2` referansini BOM/source_prompt kanitiyla normalize et:
  - Projede 2. role isteniyorsa `K2`, `OK2`, `Q2`, `D2` ve netleri tam komponent olarak ekle.
  - 2. role istenmiyorsa `K2` pinlerini netlerden kaldir.
- [x] `R10` referansini pin seviyesinde normalize et (`R10.1`, `R10.2`) veya grup referanslari `R10-R13` icinden ac.
- [x] BOM ile netlist MPN eslesmesini duzelt:
  - `PC817` <-> BOM'daki gercek PC817 MPN
  - `SS14` <-> BOM'daki gercek diode MPN
  - `G5Q-14-DC5` BOM'da varsa ayni formatta izlenebilir yap
  - `2N7002` BOM'a ekle veya netlistten cikar
- [ ] Source evidence pass olmadan KiCad generate devam edebilir ama PCBA/FAB export kilitli kalir.

## P0 - DRC=0 Hedefi ✅ TAMAMLANDI

Son verify sonucu:

```text
0 via_dangling
0 track_dangling
0 lib_footprint_issues
0 unconnected_items
total 0
```

Yapilanlar:

- [x] Via yerlestirme modelini duzelt: her via en az iki gercek track/pad/zone baglantisina sahip olmali; dangling via yasak. → `_prune_dangling_copper` zone fill sonrasi <2 katmana bagli via'lari siler.
- [x] Bos uclu (dangling) track temizligi (T-junction farkindalikli) eklendi; unconnected uretmeden.
- [x] `unconnected_items` sifirlandi; KiCad son kosuda baglanti eksigi raporlamiyor.
- [x] `OmniCircuit` footprint kutuphanesini `fp-lib-table` ve proje kutuphanesiyle kalici tanimla.
- [ ] (Kalite) Router, route kabul etmeden once via olusturma stratejisini iyilestirsin; prune yerine basta dogru via uretsin (4-katman fanout/stitching).

## P1 - 4 Katman Uretim Mimarisi

Secilen hedef mimari:

```text
L1 F.Cu   : komponent + sinyal
L2 In1.Cu : solid GND plane
L3 In2.Cu : +3V3 / +5V_ISO / +1V8 power zones
L4 B.Cu   : sinyal escape
```

Kurallar:

- [ ] RF net `UWB_RF_50R` L1'de kisa, viasiz, L2 GND referansli kalacak.
- [ ] GND ve power netleri trace-star ile degil plane + stitching via ile baglanacak.
- [ ] Sinyal router sadece L1/L4 kullanacak; In1/In2 sinyal icin yasak.
- [ ] U3 QFN escape icin pad -> kisa fanout -> via -> L4 stratejisi uygulanacak.
- [ ] AC primer bolge power plane'lerden dislanacak.

## P1 - Ollama/Gemma4 Kontrollu AI Akisi

- [x] Gemma4 cikisi bos/yetersizse deterministik fallback calissin, ama `synthesis_source` acik yazilsin. (run_ai_synthesis.py mevcut)
- [ ] LLM cikisi JSON schema, komponent sayisi, net referanslari, BOM MPN, footprint alanlari ile validate edilsin.
- [ ] LLM'in emin olmadigi footprint/pinout icin `requires_user_evidence=true` isareti koyulsun.
- [ ] Kullanici Girdi Paneli'nde eksik alan varsa UI "sorulacaklar" listesi uretilsin.

### Kapali-Dongu AI Tamir (TAMAMLANDI — bkz. [[12 - AI Tamir Döngüsü]])

- [x] `engine/ai_repair_service.py`: DRC/gate/girdi bulgularini **aktif AI saglayiciya** (ai_settings.json) ver -> `AI_NETLIST_REPAIR_V1` oneri al. (gemma4 ile dogrulandi)
- [x] Deterministik dogrulama gate (sema + guvenlik + confidence + requires_user_evidence). Test 9/9 PASS.
- [x] Candidate netlist'e uygula -> KiCad re-verify -> yalnizca iyilestirirse kabul, yoksa rollback.
- [x] `engine/input_evidence_validator.py`: Girdi Paneli (BOM<->netlist) hata tespiti -> AI'a beslenir.
- [x] Deterministik BOM hizalama (normalizer): value/MPN her build'de BOM'a hizali (R20=10K, R21=33R).
- [x] UI gosterimi: Flutter dashboard'da `_InputEvidencePanel` (girdi denetimi + sorulacaklar). `tool/run_ai_repair.ps1` eklendi. `flutter analyze` temiz.

## P2 - PCBA/FAB Guvenlik

- [x] PCBA direct export provider hatasi giderildi.
- [x] PCBA direct export source evidence ve DRC gate ile kilitlendi.
- [x] PCBA/FAB export manifest blocked veya stale ise Python gate tarafinda acilmaz.
- [ ] Fabrication ekraninda eski ZIP/JSON dosyalari son manifestle uyusmuyorsa "stale" olarak goster.
- [ ] ZIP icine manifest, DRC=0 raporu, ERC raporu, BOM, CPL, Gerber, drill, assembly drawing ve fabrication notes zorunlu eklensin.

## Uretim Kabul Kriteri

```text
design_source_evidence=pass
KiCad ERC=0 error
KiCad DRC=0 error/warning policy pass
unconnected_items=0
via_dangling=0
production_model_gate=pass
simulation_review=pass veya explicit_manual_review
engineering_readiness=production_candidate
fabrication_zip_manifest matches current board/netlist hash
```

Bu kriterler saglanmadan uygulama "uretildi", "hazir", "guvenli" veya "siparise gonderilebilir" demeyecek.
