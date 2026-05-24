from __future__ import annotations

import csv
from pathlib import Path

from engine.omnicircuit.models import BomItem, ProjectInputs


REQUIRED_FILES = ("SCHEMATIC.md", "BOM.csv", "PCB_NOTES.md")


def load_project_inputs(project_root: Path) -> ProjectInputs:
    missing = [name for name in REQUIRED_FILES if not (project_root / name).exists()]
    if missing:
        missing_names = ", ".join(missing)
        raise FileNotFoundError(f"Missing required project input file(s): {missing_names}")

    return ProjectInputs(
        schematic_text=(project_root / "SCHEMATIC.md").read_text(encoding="utf-8"),
        pcb_notes_text=(project_root / "PCB_NOTES.md").read_text(encoding="utf-8"),
        bom_items=_read_bom(project_root / "BOM.csv"),
    )


def _read_bom(path: Path) -> list[BomItem]:
    with path.open(newline="", encoding="utf-8-sig") as bom_file:
        reader = csv.DictReader(bom_file)
        return [
            BomItem(
                reference=(row.get("Reference") or "").strip(),
                quantity=_safe_int(row.get("Quantity")),
                value=(row.get("Value") or "").strip(),
                manufacturer=(row.get("Manufacturer") or "").strip(),
                part_number=(row.get("Part Number") or "").strip(),
                package=(row.get("Package") or "").strip(),
                notes=(row.get("Notes") or "").strip(),
            )
            for row in reader
        ]


def _safe_int(value: str | None) -> int:
    try:
        return int((value or "0").strip())
    except ValueError:
        return 0
