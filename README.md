# OmniCircuit AI

OmniCircuit AI is a local proof of concept for an autonomous PCB/PCBA design and manufacturing suite. The current implementation focuses on the ESP32-S3 + DWM3000 UWB Anchor example and establishes the architecture for:

- Parsing structured schematic, BOM, and PCB constraint inputs.
- Running deterministic engineering checks for RF, isolation, power, level shifting, expansion, and testability requirements.
- Producing AI design, validation, and manufacturing handoff reports.
- Presenting the project state in a Flutter dashboard.

The referenced `Corning-AI/PCBai` repository currently presents a public roadmap-style README for conversational PCB design, placement, routing, DRC, SI, and Gerber export. This workspace therefore treats PCBai as a planned adapter boundary while the local proof of concept supplies deterministic parsers and validators that can be connected to PCBai or KiCad automation later.

## Run the Local Engine

```powershell
python -m engine.run_pipeline --project-root .
```

Generated files are written to `outputs/uwb_anchor/` and the dashboard asset is written to `assets/generated/uwb_anchor_analysis.json`.

## Run the Flutter Dashboard

```powershell
C:\flutter\bin\flutter.bat pub get
C:\flutter\bin\flutter.bat run -d chrome
```

The input panel supports both manual text entry and file import. Use `Ister Dosyasi`, `BOM Yukle`, or `Teknik Not` to load text-based design inputs such as `.md`, `.csv`, `.txt`, `.json`, `.net`, `.xml`, `.yaml`, `.sch`, or `.kicad_sch` files directly into the matching field. On Windows desktop you can either browse with `Gozat` or paste a path such as `C:\Mypcb\BOM.csv` and press `Yoldan Yukle`.

## Project Layout

- `SCHEMATIC.md`, `BOM.csv`, `PCB_NOTES.md`: UWB anchor input package.
- `engine/`: Python proof-of-concept engine, including the Phase 2 KiCad automation bridge.
- `lib/`: Flutter dashboard.
- `assets/generated/`: Engine output consumed by Flutter.
- `outputs/`: Reports and manufacturing handoff placeholders.

## Phase 2 KiCad Bridge

The KiCad bridge lives in `engine/kicad_automation_service.py`. It reads `AI_Netlist_v1`, creates KiCad project artifacts, injects RF and AC safety constraints, and can run headless `kicad-cli` DRC/Gerber/drill/CPL exports when KiCad is installed.

```powershell
python -m engine.kicad_automation_service --netlist outputs/phase1/AI_NETLIST_V1.example.json --output-root outputs/kicad
```

On this Windows workspace with KiCad 10 installed, use the wrapper script:

```powershell
.\tool\run_kicad_phase2.ps1 -Export
```

For automation testing only, exports can be forced despite DRC violations:

```powershell
.\tool\run_kicad_phase2.ps1 -Export -ContinueOnDrcError
```

## Phase 3 DRC Feedback

KiCad DRC JSON can be normalized into `DRC_REPORT_V1` and converted into PCBai-style optimization penalties:

```powershell
& "C:\Program Files\KiCad\10.0\bin\python.exe" -m engine.drc_parser `
  --input outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\manufacturing\drc_report.json `
  --output outputs\phase3\DRC_REPORT_V1.json
```

The Flutter dashboard includes a `DRC` tab that reads `assets/generated/drc_report_v1.json`.

## Phase 4 Closed-Loop Layout Optimization

The layout optimizer reads normalized DRC feedback, applies conservative `pcbnew` repairs, reruns DRC, and exports manufacturing files only when the final DRC count is zero.

```powershell
.\tool\run_layout_optimizer.ps1
```

Generated status:

- `outputs/phase4/layout_optimization_status.json`
- `outputs/phase4/gerber/`
- `outputs/phase4/drill/`
- `outputs/phase4/position/pick_and_place.csv`

Current KiCad status for the UWB anchor proof of concept:

- Schematic ERC: `0` violations.
- PCB DRC: `0` violations after closed-loop optimizer.
- Manufacturing exports: Gerber, drill, and pick-and-place generated.

## Simulation and PCBA Evidence

Run deterministic first-order engineering checks:

```powershell
.\tool\run_simulation_checks.ps1
```

Run assembly/PCBA visual exports:

```powershell
.\tool\run_pcba_exports.ps1
```

Generated files include:

- `outputs/simulation/simulation_report.json`
- `outputs/simulation/simulation_report.md`
- `outputs/assembly/*.pdf`
- `outputs/assembly/*.svg`
- `outputs/assembly/pcba_preview.glb`

## Fabrication Package

Create the local PCBWay/JLCPCB-style production archive and quote estimate:

```powershell
.\tool\run_fabrication_package.ps1
```

Generated package:

- `outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip`

## Engineering Readiness Gate

DRC=0 is not enough to claim a real production-ready electronic design. Run the engineering audit to verify schematic symbols/ERC evidence, active PCB consistency, simulation evidence, PCBA handoff files, and fabrication package integrity.

```powershell
.\tool\run_engineering_audit.ps1
```

Generated files:

- `outputs/engineering/engineering_readiness_report.json`
- `assets/generated/engineering_readiness_report.json`

Latest local audit result:

- `overall_status`: `review_required`
- `readiness_percent`: `86`
- blockers: `0`
- review warnings: `1` simulation/stackup review item
