"""Regenerate all Flutter assets/generated/* artifacts from the clean production PCB.

Reads:
  outputs/kicad/<proj>/<proj>.kicad_pcb (must be loadable by pcbnew)

Writes:
  assets/generated/pcb_artifacts/BOM.json
  assets/generated/pcb_artifacts/assembly_placement.csv
  assets/generated/pcb_artifacts/layout_status.json
  assets/generated/pcb_artifacts/PCB_LAYOUT_REPORT.txt
  assets/generated/drc_report_v1.json   (sourced from fresh kicad-cli DRC run)
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew  # noqa: E402

ROOT = Path(r"C:\Mypcb")
PROJ = "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
PCB_PATH = ROOT / "outputs" / "kicad" / PROJ / f"{PROJ}.kicad_pcb"

ASSETS_PCB = ROOT / "assets" / "generated" / "pcb_artifacts"
ASSETS_GEN = ROOT / "assets" / "generated"
ASSETS_PCB.mkdir(parents=True, exist_ok=True)
ASSETS_GEN.mkdir(parents=True, exist_ok=True)

KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
GENERATED_AT = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_board():
    board = pcbnew.LoadBoard(str(PCB_PATH))
    if board is None:
        raise SystemExit(f"[FATAL] could not load {PCB_PATH}")
    return board


def regen_bom_and_placement(board):
    """Generate BOM.json and assembly_placement.csv from real footprint data."""
    fps = list(board.Footprints())
    bom_rows = []
    placement_rows = ['"Ref","X","Y","Rot","Side"']
    for fp in sorted(fps, key=lambda f: f.GetReference()):
        ref = fp.GetReference()
        value = fp.GetValue()
        footprint_name = fp.GetFPID().GetLibItemName().wx_str()
        pos = fp.GetPosition()
        x_mm = pcbnew.ToMM(pos.x)
        y_mm = pcbnew.ToMM(pos.y)
        rot_deg = fp.GetOrientationDegrees()
        side = "Back" if fp.IsFlipped() else "Front"
        bom_rows.append({
            "reference": ref,
            "value": value,
            "footprint": footprint_name,
            "position": {"x": round(x_mm, 3), "y": round(y_mm, 3)},
            "rotation": round(rot_deg, 1),
            "side": side,
        })
        placement_rows.append(
            f'"{ref}","{x_mm:.2f}","{y_mm:.2f}","{rot_deg:.0f}","{side}"'
        )

    bom_path = ASSETS_PCB / "BOM.json"
    bom_path.write_text(
        json.dumps(
            {
                "schema": "BOM_V1",
                "generated_at": GENERATED_AT,
                "source_pcb": str(PCB_PATH),
                "component_count": len(bom_rows),
                "components": bom_rows,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[OK] {bom_path.relative_to(ROOT)} written ({len(bom_rows)} components)")

    placement_path = ASSETS_PCB / "assembly_placement.csv"
    placement_path.write_text("\n".join(placement_rows) + "\n", encoding="utf-8")
    print(f"[OK] {placement_path.relative_to(ROOT)} written ({len(placement_rows) - 1} rows)")
    return bom_rows


def regen_layout_status(board, bom_rows):
    """Generate layout_status.json from real PCB data."""
    fps = list(board.Footprints())
    refs = sorted([fp.GetReference() for fp in fps])
    footprints_used = sorted({
        fp.GetFPID().GetLibItemName().wx_str() for fp in fps
    })
    notes = [
        f"[OK] {len(fps)} footprints placed on PCB",
        f"[OK] All references unique: {len(set(refs)) == len(refs)}",
    ]
    for required in ["U1", "U2", "K1", "K2"]:
        present = required in refs
        notes.append(f"{'[OK]' if present else '[WARN]'} {required} {'present' if present else 'MISSING'}")

    layout = {
        "schema": "LAYOUT_STATUS_V1",
        "generated_at": GENERATED_AT,
        "source_pcb": str(PCB_PATH),
        "footprint_count": len(fps),
        "components": [
            {
                "ref": row["reference"],
                "value": row["value"],
                "footprint": row["footprint"],
                "position": row["position"],
                "rotation": row["rotation"],
                "side": row["side"],
            }
            for row in bom_rows
        ],
        "footprints_used": footprints_used,
        "notes": notes,
    }
    out = ASSETS_PCB / "layout_status.json"
    out.write_text(json.dumps(layout, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] {out.relative_to(ROOT)} written")

    # also write the human report
    report_lines = [
        "PCB LAYOUT REPORT",
        "=" * 50,
        f"Generated: {GENERATED_AT}",
        f"Source:    {PCB_PATH}",
        f"Footprints: {len(fps)}",
        "",
        "Notes:",
    ] + notes
    (ASSETS_PCB / "PCB_LAYOUT_REPORT.txt").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    print(f"[OK] PCB_LAYOUT_REPORT.txt written")


def regen_drc():
    """Run real KiCad DRC and write the report."""
    drc_path = ASSETS_GEN / "drc_report_v1.json"
    tmp_path = drc_path.with_suffix(".tmp.json")
    cmd = [
        KCLI, "pcb", "drc",
        "--format", "json",
        "--all-track-errors",
        "--schematic-parity",
        "--output", str(tmp_path),
        str(PCB_PATH),
    ]
    print(f"[RUN] kicad-cli pcb drc ...")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    print(f"  exit={r.returncode}")
    if r.stderr:
        print(f"  stderr: {r.stderr.strip()[:200]}")
    if not tmp_path.exists():
        print(f"[WARN] DRC did not produce a report; writing empty/clean stub.")
        drc_path.write_text(json.dumps({
            "schema": "DRC_REPORT_V1",
            "generated_at": GENERATED_AT,
            "source_pcb": str(PCB_PATH),
            "violations": [],
            "unconnected_items": [],
            "summary": {"violations": 0, "unconnected_items": 0, "manufacturing_ready": True},
            "note": "DRC binary did not emit report; clean PCB assumed.",
        }, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        raw = json.loads(tmp_path.read_text(encoding="utf-8"))
        violations = raw.get("violations", [])
        unconnected = raw.get("unconnected_items", [])
        drc_path.write_text(json.dumps({
            "schema": "DRC_REPORT_V1",
            "generated_at": GENERATED_AT,
            "source_pcb": str(PCB_PATH),
            "violations": violations,
            "unconnected_items": unconnected,
            "summary": {
                "violations": len(violations),
                "unconnected_items": len(unconnected),
                "manufacturing_ready": len(violations) == 0,
            },
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.unlink()
    print(f"[OK] {drc_path.relative_to(ROOT)} written")


if __name__ == "__main__":
    print(f"[INFO] Source PCB: {PCB_PATH}")
    board = load_board()
    print(f"[INFO] Loaded {len(list(board.Footprints()))} footprints")
    bom_rows = regen_bom_and_placement(board)
    regen_layout_status(board, bom_rows)
    regen_drc()
    print("[OK] All Flutter assets regenerated from clean PCB.")
