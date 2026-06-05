"""Standalone driver for KicadAutomationService._prune_dangling_copper().

Loads the production PCB via pcbnew, calls the project's existing prune routine,
saves it back. Repeats DRC check via kicad-cli to confirm cleanliness.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
sys.path.insert(0, r"C:\Mypcb")

import pcbnew  # noqa: E402

# Import the service (it brings KicadAutomationService into scope)
from engine.kicad_automation_service import KiCadAutomationService  # noqa: E402

PCB = Path(r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb")

board = pcbnew.LoadBoard(str(PCB))
if board is None:
    raise SystemExit(f"[FATAL] could not load {PCB}")

tracks_before = len(list(board.GetTracks()))
vias_before = sum(1 for t in board.GetTracks() if isinstance(t, pcbnew.PCB_VIA))
print(f"[INFO] Before prune: {tracks_before} tracks (incl. {vias_before} vias)")

svc = KiCadAutomationService()
removed = svc._prune_dangling_copper(pcbnew, board)
print(f"[INFO] Prune removed {removed} dangling items")

if not pcbnew.SaveBoard(str(PCB), board):
    raise SystemExit("[FATAL] SaveBoard failed")

# Reload for verification
verify = pcbnew.LoadBoard(str(PCB))
tracks_after = len(list(verify.GetTracks()))
vias_after = sum(1 for t in verify.GetTracks() if isinstance(t, pcbnew.PCB_VIA))
print(f"[INFO] After  prune: {tracks_after} tracks (incl. {vias_after} vias)")

# Re-run DRC to confirm
kcli = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
drc_out = PCB.parent / "manufacturing" / "drc_report_post_prune.json"
drc_out.parent.mkdir(parents=True, exist_ok=True)
r = subprocess.run(
    [kcli, "pcb", "drc", "--format", "json", "--all-track-errors",
     "--schematic-parity", "--output", str(drc_out), str(PCB)],
    capture_output=True, text=True, timeout=180,
)
print(f"[DRC] exit={r.returncode}")
if drc_out.exists():
    import json
    rep = json.loads(drc_out.read_text(encoding="utf-8"))
    viols = rep.get("violations", [])
    unconn = rep.get("unconnected_items", [])
    types: dict[str, int] = {}
    for v in viols:
        t = v.get("type", "?")
        types[t] = types.get(t, 0) + 1
    print(f"[DRC] violations={len(viols)}  unconnected={len(unconn)}")
    print(f"[DRC] types={types}")
