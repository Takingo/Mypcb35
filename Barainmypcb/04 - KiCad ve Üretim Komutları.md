---
title: KiCad ve Uretim Komutlari
tags:
  - commands
  - kicad
  - manufacturing
status: active
updated: 2026-05-26
---

# KiCad ve Uretim Komutlari

## Ortam

```text
KiCad CLI:    C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
KiCad Python: C:\Program Files\KiCad\10.0\bin\python.exe
KiCad:        10.0.3
Python:       3.11.5
```

## Faz 2 - KiCad Proje Uretimi

```powershell
.\tool\run_kicad_phase2.ps1 -Export
```

Guncel beklenen sonuc:

```text
DRC pass
Son verify raporu: total 0 (0 via_dangling, 0 track_dangling, 0 unconnected_items, 0 error)
manufacturing_ready=true
Gerber/drill/position uretildi
```

DRC hatalarina ragmen export testi:

```powershell
.\tool\run_kicad_phase2.ps1 -Export -ContinueOnDrcError
```

> [!warning]
> `-ContinueOnDrcError` sadece otomasyon testi icindir. Uretime gonderilecek paket icin kullanilmaz.

## Faz 4 - Closed-Loop Optimizer

```powershell
.\tool\run_layout_optimizer.ps1
```

Son davranis:

```text
22 -> 507 denemesi kotulestirdi
rollback yapildi
manufacturing_ready=false
```

## AI Tamir + Girdi Kanit Dogrulama

```powershell
.\tool\run_ai_repair.ps1            # girdi denetimi + AI oneri (dry-run)
.\tool\run_ai_repair.ps1 -Apply     # candidate'i KiCad re-verify ile dogrula, regresyon yoksa uygula
```

Cikti: `outputs/engineering/input_evidence_report.json` + `ai_repair_log.json` (UI okur). Bkz. [[12 - AI Tamir Döngüsü]].

## Muhendislik Audit

```powershell
.\tool\run_engineering_audit.ps1
```

Guncel sonuc:

```text
overall_status=review_required
readiness_percent=89
passed=8/9
blockers=0
review=1 (REAL_SIMULATION)
```

## Faz 5 - Uretim Paketi

```powershell
.\tool\run_fabrication_package.ps1
```

Guncel beklenen sonuc:

```text
status: package_ready
outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip (~18 KB)
```

DRC=0 + model gate + source evidence gectigi icin paket uretiliyor. Fiziksel siparis oncesi engineering review + uretici DFM tavsiye edilir.

## Python Testleri

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" test\kicad_routing_python_test.py
& "C:\Program Files\KiCad\10.0\bin\python.exe" test\engineering_gate_python_test.py
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m py_compile engine\kicad_automation_service.py engine\layout_optimizer_service.py engine\engineering_readiness_service.py engine\fabrication_api_service.py engine\production_model_gate.py
```

## Flutter

```powershell
C:\flutter\bin\flutter.bat run -d chrome
C:\flutter\bin\flutter.bat run -d windows
C:\flutter\bin\flutter.bat build windows
```

Flutter testleri son turda bilincli olarak tam calistirilmadi; KiCad ve gate testleri onceliklendirildi.

## Guncel Kanit Dosyalari

```text
outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs/manufacturing/drc_report.json
outputs/phase4/layout_optimization_status.json
outputs/engineering/engineering_readiness_report.json
assets/generated/drc_report_v1.json
assets/generated/engineering_readiness_report.json
```
