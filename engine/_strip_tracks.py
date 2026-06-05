"""Strip ALL track segments and vias from the current PCB.

Why: Phase 2 (KiCad generation) sometimes leaves the board with pre-routed
fragments that confuse Freerouting (the DSN reader warns "normalization
of net X failed" and pops a modal dialog).  By removing every track/via
before handing the board to Freerouting, we force it to route from scratch
with a clean topology.

Footprints, zones, and pads are preserved.
"""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

board = pcbnew.LoadBoard(PCB)
tracks_before = list(board.GetTracks())
n_tracks = sum(1 for t in tracks_before if not isinstance(t, pcbnew.PCB_VIA))
n_vias = sum(1 for t in tracks_before if isinstance(t, pcbnew.PCB_VIA))
print(f"[STRIP] before: {n_tracks} tracks + {n_vias} vias")

for t in tracks_before:
    board.Remove(t)

pcbnew.SaveBoard(PCB, board)
print(f"[STRIP] OK — removed {n_tracks + n_vias} item(s), PCB saved.")
