from __future__ import annotations

import argparse
from pathlib import Path

from omnicircuit.input_loader import load_project_inputs
from omnicircuit.report_writer import write_outputs
from omnicircuit.uwb_anchor_rules import evaluate_uwb_anchor


def run(project_root: Path) -> int:
    inputs = load_project_inputs(project_root)
    analysis = evaluate_uwb_anchor(inputs)
    write_outputs(project_root, analysis)
    print(f"OmniCircuit AI generated {len(analysis.checks)} validation checks.")
    print(f"Overall status: {analysis.overall_status}")
    print(f"Reports: {project_root / 'outputs' / analysis.project_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the OmniCircuit AI local pipeline.")
    parser.add_argument(
        "--project-root",
        default=".",
        help="Directory containing SCHEMATIC.md, BOM.csv, and PCB_NOTES.md.",
    )
    args = parser.parse_args()
    return run(Path(args.project_root).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
