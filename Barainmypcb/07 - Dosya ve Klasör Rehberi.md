---
title: Dosya ve Klasor Rehberi
tags:
  - files
  - guide
  - project
status: active
updated: 2026-05-26
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
| `engine/cognitive_netlist_generator.py` | AI netlist uretimi |
| `engine/kicad_automation_service.py` | KiCad proje, footprint, pin-pad ve DRC koprusu |
| `engine/drc_parser.py` | KiCad DRC JSON -> DRC_REPORT_V1 |
| `engine/layout_optimizer_service.py` | Closed-loop DRC duzeltme ve rollback |
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
