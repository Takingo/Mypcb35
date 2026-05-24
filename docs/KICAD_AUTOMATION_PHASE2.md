# OmniCircuit AI Phase 2: KiCad Automation Bridge

`engine/kicad_automation_service.py` converts `AI_Netlist_v1` into a KiCad project directory and, when KiCad is installed, runs headless manufacturing exports.

## Responsibilities

- Read `AI_NETLIST_V1.example.json`.
- Generate `.kicad_pro`, draft `.kicad_sch`, and `.kicad_pcb`.
- Use KiCad `pcbnew` when available to create board geometry and footprints.
- Force the DWM3000 module footprint to 1.0mm pad pitch.
- Create RF and mains-oriented rule metadata.
- Create an 8mm AC keepout/rule area around the mains input zone.
- Run `kicad-cli` DRC, Gerber, drill, and position exports.

## Usage

```powershell
python -m engine.kicad_automation_service `
  --netlist outputs/phase1/AI_NETLIST_V1.example.json `
  --output-root outputs/kicad
```

To run manufacturing exports:

```powershell
python -m engine.kicad_automation_service `
  --netlist outputs/phase1/AI_NETLIST_V1.example.json `
  --output-root outputs/kicad `
  --export
```

## Environment Requirements

- Python with access to KiCad's `pcbnew` module.
- `kicad-cli` available on PATH, or passed with `--kicad-cli`.
- Final manufacturing release still requires a human electronics review for AC safety, RF impedance, DRC/ERC, and supplier-specific DFM.
