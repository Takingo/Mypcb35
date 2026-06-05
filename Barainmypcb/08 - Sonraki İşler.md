---
title: Sonraki Isler
tags:
  - roadmap
  - blockers
  - production
status: active
updated: 2026-05-30
---

# Sonraki Isler

> [!success] Sistem Durumu (2026-05-30)
> Production state: `production_candidate`, DRC `0/0/0/0`, `manufacturing_ready=true`, ZIP `package_ready` (157 KB, 29 dosya, 09:20 itibariyla disk uzerinde). Hayalet C99-C102 PCB+sematik+asset+manifest seviyesinde gercek olarak temizlendi. HITL sistemi ([[13 - HITL Insan Donguye Dahil]]) devrede.

## 2026-05-30 Aktif Blocker

- **DevKit Conversion (placement)**: HITL pause durumunda. `assets/generated/hitl_state.json` icinde A/B/C/D secenekleri muhendis cevabini bekliyor. Production ZIP (SMD WROOM) bu pause'dan etkilenmez.
- **240 schematic parity warning**: PCB net listesi ile sematik arasinda C99-C102 cleanup sonrasi divergence. Bilgilendirici; KiCad GUI'de eeschema "Update PCB from Schematic" ile cozulebilir. DRC error olarak sayilmiyor (manufacturing_ready=true devam).

## P0 - Once Gercegi Tekilleştir

- [x] `board_verification_manifest.json` ekle: netlist hash, PCB hash, KiCad version, DRC count, unconnected count.
- [x] `run_kicad_phase2.ps1` ve `engineering_readiness_report.json` board manifest ile beslensin.
- [x] **Stale asset purge** (2026-05-30): `outputs/kicad_verify/`, `outputs/kicad_baseline/`, `outputs/kicad_test/`, `outputs/kicad/industrial_uwb_*/` silindi (~2.5MB). `assets/generated/pcb_artifacts/*` ve `drc_report_v1.json` temiz PCB'den `engine/_regenerate_assets.py` ile yeniden uretildi. Flutter UI artik C99-C102 hayalet komponentlerini gostermeyecek.
- [x] **Yalanci dokuman silme** (2026-05-30): `MANUFACTURING_COMPLETE.txt`, `PCBA_STATUS_FINAL.txt`, `outputs/phase4/*iteration_1*` silindi.
- [ ] `verify_board.ps1` ve UI stale-status gostergesi manifest politikasina tamamen baglansin.
- [ ] Brainmypcb otomatik rapor yazici ekle; eski `331`, `6`, `26/25` gibi stale sayilar tekrar kalmasin.
- [ ] UI'da stale asset varsa "gecersiz/eski rapor" olarak goster.

## P0 - 2026-05-30 Yapilanlar (Hayalet Temizligi + HITL)

- [x] **C99-C102 PCB temizligi (pcbnew API)**: `engine/_clean_pcb_proper.py` — `pcbnew.LoadBoard().Remove(footprint)` ile yapisal integriteyi koruyarak 4 footprint silindi. Eski bash surgery'nin yarattigi corruption (parens -5, 13K negative dive) `ca68ad2` restore + proper API removal ile cozuldu.
- [x] **C99-C102 sematik temizligi**: `engine/_clean_sch_proper.py` — S-expression scanner ile 8 (symbol) blogu (4 lib_symbols entry + 4 instance) snip edildi; parens balance=0.
- [x] **Dangling copper prune (subprocess loop)**: SWIG proxy invalidation bug'i nedeniyle in-process loop crash ediyordu. `engine/_prune_one.py` her pass'i fresh subprocess olarak calistirir. 4+8+11+9+4+4+7+7=70 oge silindi (full chain) ya da 6+2+2+3+2+1=16 oge (post-rollback chain).
- [x] **U7.5 orphan +3V3 koprusu**: `engine/_route_orphan_3v3.py` — F.Cu 0.25mm track U7.5 → U8.1 (6.99mm). Ghost C99-C102 decoupler bypass'inin yerine kondu.
- [x] **Zone refill**: `engine/_zone_fill.py` — `pcbnew.ZONE_FILLER(board).Fill(zones)`. GND ve +3V3 polygon flood'lari same-net island'leri otomatik birlestiriyor.
- [x] **DRC = 0**: Tam temiz. `outputs/kicad/.../manufacturing/drc_report.json` SHA: `48de90ef...` (oturum icinde degisebilir).
- [x] **Manifest project's-own-writer**: `PYTHONPATH="engine"` + KiCad Python ile `engine/board_verification_manifest.py` calistirildi. `production_model_pass=true`, `source_evidence_pass=true`, manufacturing_ready=true.
- [x] **Fab ZIP repack**: `engine/fabrication_api_service.py` package_ready, `outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip` (157 KB, 29 dosya).
- [x] **BOM-strict prompt**: `engine/cognitive_netlist_generator.py:SYSTEM_PROMPT` basinda "ABSOLUTE BOM LAW" — AI artik BOM disi component ref uretemez (FATAL SYSTEM ERROR). REUSE — never INVENT kurali.
- [x] **DesignRule.net_class resilience**: `_safe_unpack()` helper + `net_class: str | None = None` optional alan. AI extra alanlari sessizce dropluyor; fallback'a dusmuyor.
- [x] **zfill regression squash**: `ai_error_corrector.py:201` `f"PROP_{len(str(finding_id)).zfill(3)}"` (int.zfill crash) -> `proposal_id` reuse. PROP_007 dogru uretiliyor.
- [x] **UTF-8 patch**: `run_ai_synthesis.py` + `ai_error_corrector.py` `sys.stdout.reconfigure(encoding='utf-8')` ile basina enjekte. `pcb_layout_generator.py` 3 noktada `open(..., encoding='utf-8')`. Turkce karakter charmap crash'i bitti.
- [x] **MOV1 netlist consistency**: `outputs/phase1/AI_NETLIST_V1.json` icinde RV1.* pin referanslari MOV1.* olarak rename + MOV1 component eklendi. Source evidence gate gecti.
- [x] **HITL module**: `engine/hitl_manager.py` — `ask_human_engineer(blocker_type, question, context, suggested_choices)`. JSON state/answer/log dosyalari. Detay: [[13 - HITL Insan Donguye Dahil]].

## P1 - DevKit Conversion (HITL pause)

- [x] **Surgical pcbnew swap denemesi**: U1 SMD WROOM kaldirildi, 2× PinHeader_1x22_P2.54mm_Vertical (90° rotate) eklendi, 6 signal stitch edildi, 5 komsu (R10-R13, K2) relocate edildi. **Sonuc**: 43 DRC violation.
- [x] **Forward-fix iteration 1**: via-drop + B.Cu fallback routing ile auto-route denendi. **Sonuc**: 196 violation (DIVERGENCE — 4.5x kotulesti). Durduruldu.
- [x] **Honest rollback**: `git checkout ca68ad2 -- *.kicad_pcb *.kicad_sch` + clean chain replay. Production state restore edildi.
- [x] **HITL blocker emit**: DevKit placement icin A/B/C/D secenekleri ile `hitl_state.json` yazildi. Engineer cevabi bekleniyor.
- [ ] **Dersler**: pcbnew Python API push-and-shove router'a sahip degil. Dense layout'ta agir auto-routing pcbnew script'ten guvenli yapilamaz. Cozum yollari: (a) KiCad GUI'de manuel route, (b) FreeRoute integration, (c) HITL ile her routing kararini muhendise sor.

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
