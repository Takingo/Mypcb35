---
title: Dosya ve Klasör Rehberi
tags:
  - files
  - guide
  - project
status: active
---

# Dosya ve Klasör Rehberi

## Kök Dosyalar

| Dosya | Açıklama |
| --- | --- |
| `BOM.csv` | Komponent listesi |
| `SCHEMATIC.md` | Örnek devre bağlantı açıklaması |
| `PCB_NOTES.md` | PCB kuralları, RF, izolasyon ve test notları |
| `README.md` | Genel çalışma talimatları |
| `pubspec.yaml` | Flutter proje bağımlılıkları ve asset listesi |

## Engine

```text
engine/
```

| Dosya | Görev |
| --- | --- |
| `cognitive_netlist_generator.py` | AI netlist üretimi |
| `kicad_automation_service.py` | KiCad proje ve export bridge |
| `drc_parser.py` | KiCad DRC JSON → DRC_REPORT_V1 |
| `pcbai_feedback_adapter.py` | DRC → PCBai penalty payload |
| `layout_optimizer_service.py` | Closed-loop DRC düzeltme |
| `fabrication_api_service.py` | Üretim ZIP paketi ve checkout özeti |
| `run_pipeline.py` | Eski lokal rapor pipeline |

## Flutter

```text
lib/
```

| Dosya | Görev |
| --- | --- |
| `main.dart` | App giriş noktası |
| `omnicircuit_dashboard.dart` | Ana dashboard UI |
| `manufacturing_dashboard.dart` | Üretim ve sipariş hazırlığı UI |
| `controllers/netlist_controller.dart` | UI state yönetimi |
| `models/ai_netlist.dart` | Netlist modeli |
| `models/design_package.dart` | Design package, DRC ve optimizer modelleri |
| `services/cognitive_netlist_service.dart` | Flutter tarafı netlist servis mock/logic |
| `services/input_file_import_service.dart` | `.md`, `.csv`, `.txt`, `.json`, `.net`, `.xml`, `.yaml`, `.sch`, `.kicad_sch` giriş dosyalarını UI alanlarına yükler |

## Tool Scripts

```text
tool/
```

| Dosya | Görev |
| --- | --- |
| `run_kicad_phase2.ps1` | KiCad proje + DRC/export bridge |
| `run_layout_optimizer.ps1` | Closed-loop optimizer |
| `run_fabrication_package.ps1` | Üretim ZIP paketi üretimi |
| `serve_web.dart` | Flutter web build static server |

## Outputs

```text
outputs/
```

| Klasör | Açıklama |
| --- | --- |
| `outputs/phase1/` | AI netlist örneği |
| `outputs/kicad/` | KiCad proje dosyaları |
| `outputs/phase3/` | DRC_REPORT ve PCBai feedback |
| `outputs/phase4/` | optimizer sonucu ve üretim dosyaları |
| `outputs/fabrication/` | üretim ZIP paketi ve checkout özeti |
| `outputs/uwb_anchor/` | eski rapor/manufacturing scaffold |

## Assets

```text
assets/generated/
```

Flutter tarafından okunan dosyalar:

- `uwb_anchor_analysis.json`
- `drc_report_v1.json`
- `layout_optimization_status.json`
- `fabrication_package.json`

## Obsidian Hafızası

```text
Barainmypcb/
```

Bu klasör proje bilgisini takip etmek için oluşturulmuştur. Ana başlangıç notu:

[[00 - OmniCircuit AI Ana Harita]]
