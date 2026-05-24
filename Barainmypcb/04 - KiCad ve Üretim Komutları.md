---
title: KiCad ve Üretim Komutları
tags:
  - commands
  - kicad
  - manufacturing
status: active
---

# KiCad ve Üretim Komutları

## Ortam

KiCad yolu:

```text
C:\Program Files\KiCad\10.0\bin
```

KiCad CLI:

```text
C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
```

KiCad Python:

```text
C:\Program Files\KiCad\10.0\bin\python.exe
```

Doğrulanan versiyon:

```text
KiCad 10.0.3
Python 3.11.5
```

## Faz 2 - KiCad Proje Üretimi

```powershell
.\tool\run_kicad_phase2.ps1
```

DRC ve export denemesi:

```powershell
.\tool\run_kicad_phase2.ps1 -Export
```

DRC hatalarına rağmen export test etmek için:

```powershell
.\tool\run_kicad_phase2.ps1 -Export -ContinueOnDrcError
```

> [!warning]
> `-ContinueOnDrcError` sadece otomasyon testi içindir. Üretime gönderilecek dosya için kullanılmamalıdır.

## Faz 3 - DRC Rapor Normalize Etme

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m engine.drc_parser `
  --input outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\manufacturing\drc_report.json `
  --output outputs\phase3\DRC_REPORT_V1.json
```

## Faz 4 - Closed-Loop Optimizer

```powershell
.\tool\run_layout_optimizer.ps1
```

Varsayılan olarak şunu optimize eder:

```text
outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb
```

## Faz 5 - Üretim Paketi Hazırlama

```powershell
.\tool\run_fabrication_package.ps1
```

Opsiyonel seçimlerle:

```powershell
.\tool\run_fabrication_package.ps1 -Quantity 10 -Manufacturer PCBWay -SolderMaskColor Black
```

Bu komut dış servise veri göndermez. Şunları üretir:

```text
outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip
outputs/fabrication/fabrication_package.json
assets/generated/fabrication_package.json
```

Flutter'da üretim checkout ekranı ana sayfadaki kamyon ikonundan açılır.

## Flutter Dashboard

Chrome:

```powershell
C:\flutter\bin\flutter.bat run -d chrome
```

Windows desktop:

```powershell
C:\flutter\bin\flutter.bat run -d windows
```

Build:

```powershell
C:\flutter\bin\flutter.bat build windows
```

## Testler

```powershell
C:\flutter\bin\flutter.bat analyze
C:\flutter\bin\flutter.bat test
```

## Üretim Çıktıları

```text
outputs/phase4/gerber/
outputs/phase4/drill/
outputs/phase4/position/pick_and_place.csv
outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip
```

Detaylı güvenlik kontrolü için bkz. [[06 - Güvenlik ve Üretime Hazırlık]].
