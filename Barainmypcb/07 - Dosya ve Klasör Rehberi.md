---
title: Dosya ve Klasor Rehberi
tags:
  - files
  - guide
  - project
status: active
updated: 2026-05-30
---

# Dosya ve Klasor Rehberi

## Kok Dosyalar

| Dosya | Aciklama |
| --- | --- |
| `BOM.csv` | Komponent listesi |
| `SCHEMATIC.md` | Ornek devre baglanti aciklamasi |
| `PCB_NOTES.md` | PCB kurallari, RF, izolasyon ve test notlari |
| `README.md` | Genel calisma talimatlari |
| `pubspec.yaml` | Flutter proje bagimliliklari ve asset listesi |

## Engine

| Dosya | Gorev |
| --- | --- |
| `engine/cognitive_netlist_generator.py` | AI netlist uretimi (2026-05-30: ABSOLUTE BOM LAW prompt + `_safe_unpack()` resilience + `net_class` optional alani) |
| `engine/kicad_automation_service.py` | KiCad proje, footprint, pin-pad ve DRC koprusu (`_prune_dangling_copper` — subprocess loop'ta `engine/_prune_one.py` uzerinden cagrilir) |
| `engine/drc_parser.py` | KiCad DRC JSON -> DRC_REPORT_V1 |
| `engine/layout_optimizer_service.py` | Closed-loop DRC duzeltme ve rollback |
| `engine/hitl_manager.py` | **YENİ (2026-05-30)** — Human-in-the-Loop API: `ask_human_engineer()`, JSON state/answer/log dosyalari. Bkz. [[13 - HITL Insan Donguye Dahil]] |
| `engine/ai_error_corrector.py` | AI hata duzeltme onerileri (2026-05-30: zfill regression squash line 201 + UTF-8 reconfigure header) |
| `engine/run_ai_synthesis.py` | Sentez entry point (2026-05-30: UTF-8 reconfigure + phase1 netlist save on both real_ai ve fallback path) |
| `engine/pcb_layout_generator.py` | PCB layout/BOM generator (2026-05-30: 3 noktada `open(..., encoding='utf-8')`) |

### Bu Oturumda Eklenen Tek-Atışlık Tool Script'leri (2026-05-30)

| Script | Gorev |
| --- | --- |
| `engine/_clean_pcb_proper.py` | pcbnew API ile C99-C102 footprint silme (yapısal-integrite koruyucu) |
| `engine/_clean_sch_proper.py` | S-expression scanner ile sematik C99-C102 (symbol) bloglarini silme |
| `engine/_prune_one.py` | Tek pass dangling-copper prune (subprocess loop ile SWIG bug bypass) |
| `engine/_zone_fill.py` | `pcbnew.ZONE_FILLER` ile 8 zone refill |
| `engine/_route_orphan_3v3.py` | U7.5 → U8.1 F.Cu 6.99mm +3V3 koprusu (ghost decoupler bypass yerine) |
| `engine/_regenerate_assets.py` | Temiz PCB'den Flutter UI asset'lerini yeniden uretir (BOM.json, layout_status.json, drc_report_v1.json, vd.) |
| `engine/_update_manifest.py` | Custom manifest writer (oturum içi geçici; final manifest `engine/board_verification_manifest.py` ile uretildi) |
| `engine/_inspect_u1.py` | U1 pad-net mapping cikartma → `_u1_padmap.json` |
| `engine/_swap_u1_to_devkit.py` | DevKit conversion attempt (rollback edildi — pcbnew Python API auto-route limit'i sergilendi) |
| `engine/_fix_devkit_orientation.py` | DevKit sockets 90° rotate + reposition (attempt deneyiminin parcasi) |
| `engine/_stitch_devkit_signals.py` | DevKit signal nets Manhattan stitch (attempt) |
| `engine/_smart_fix_iter.py` | Forward-fix iteration (43→196 violation divergence kanitladi; rolled back) |
| `engine/_paren_scan.py` | S-expression paren balance debug |
| `engine/_debug_prune.py` / `_inline_prune.py` / `_run_prune.py` | Prune routine debug variants |
| `engine/production_model_gate.py` | Sentetik footprint/no-net pad uretim modeli kapisi |
| `engine/engineering_readiness_service.py` | Uretim adayligi denetimi |
| `engine/fabrication_api_service.py` | Gate gecerse yerel uretim ZIP paketi |
| `engine/pcba_manufacturing_export_service.py` | PCBA manufacturing export yardimci servisi |

## Flutter

| Dosya | Gorev |
| --- | --- |
| `lib/main.dart` | App giris noktasi |
| `lib/omnicircuit_dashboard.dart` | Ana dashboard UI |
| `lib/manufacturing_dashboard.dart` | Uretim ve checkout UI |
| `lib/controllers/netlist_controller.dart` | UI state yonetimi |
| `lib/services/input_file_import_service.dart` | Girdi/BOM dosyalarini UI alanlarina yukler |
| `lib/services/kicad_pipeline_service.dart` | KiCad pipeline durumlari |

## Tool Scripts

| Dosya | Gorev | Guncel not |
| --- | --- | --- |
| `tool/run_kicad_phase2.ps1` | KiCad proje + DRC/export bridge | Son verify DRC total 20 |
| `tool/run_layout_optimizer.ps1` | Closed-loop optimizer | Kotu sonucu rollback yapiyor |
| `tool/run_engineering_audit.ps1` | Readiness raporu | Son durum blocked |
| `tool/run_fabrication_package.ps1` | Uretim ZIP paketi | Su anda gate tarafindan bloklaniyor |
| `tool/render_board_views.ps1` | SVG board gorunumleri | Yardimci gorsel cikti |

## Outputs

| Klasor/Dosya | Aciklama |
| --- | --- |
| `outputs/phase1/AI_NETLIST_V1.json` | Aktif kullanici netlist kaynagi |
| `outputs/kicad/` | KiCad proje dosyalari |
| `outputs/kicad/.../manufacturing/drc_report.json` | Gercek KiCad DRC raporu |
| `outputs/phase4/layout_optimization_status.json` | Optimizer ve manufacturing_ready durumu |
| `outputs/engineering/engineering_readiness_report.json` | Son engineering gate raporu |
| `outputs/fabrication/` | Eski/onceki paketler bulunabilir; son gate blocked ise uretim onayi degildir |

## Assets

Flutter tarafindan okunan dosyalar:

- `assets/generated/drc_report_v1.json`
- `assets/generated/layout_optimization_status.json`
- `assets/generated/engineering_readiness_report.json`
- `assets/generated/fabrication_package.json`

> [!warning]
> `fabrication_package.json` veya ZIP dosyasinin diskte bulunmasi tek basina uretim onayi degildir. Son `engineering_readiness_report.json` `blocked` ise paket gecersiz/stale kabul edilmelidir.

## Obsidian Hafizasi

```text
Barainmypcb/
```

Ana baslangic notu:

[[00 - OmniCircuit AI Ana Harita]]
