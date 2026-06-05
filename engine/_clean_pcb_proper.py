"""Properly remove C99/C100/C101/C102 footprints from PCB via pcbnew API.

Unlike the bash surgery in commit a2307a4, this preserves S-expression integrity
because it uses pcbnew's own DSL-aware footprint deletion + re-save.
"""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
GHOSTS = {"C99", "C100", "C101", "C102"}

board = pcbnew.LoadBoard(PCB)
if board is None:
    print(f"[FATAL] could not load board {PCB}")
    sys.exit(1)

before = [fp.GetReference() for fp in board.Footprints()]
print(f"[INFO] Footprints before: {len(before)}")
removed = []
for fp in list(board.Footprints()):
    ref = fp.GetReference()
    if ref in GHOSTS:
        board.Remove(fp)
        removed.append(ref)

print(f"[INFO] Removed: {removed}")

if not pcbnew.SaveBoard(PCB, board):
    print("[FATAL] SaveBoard failed")
    sys.exit(2)

# Reload to verify
verify = pcbnew.LoadBoard(PCB)
after = sorted([fp.GetReference() for fp in verify.Footprints()],
               key=lambda r: (r[0], int(''.join(c for c in r[1:] if c.isdigit()) or 0)))
crefs = sorted([r for r in after if r.startswith("C")],
               key=lambda r: int(r[1:]))
print(f"[INFO] Footprints after:  {len(after)}")
print(f"[INFO] C-refs after:      {crefs}")
remaining_ghosts = [g for g in GHOSTS if g in after]
print(f"[INFO] Ghosts still present: {remaining_ghosts}")
if remaining_ghosts:
    sys.exit(3)
print("[OK] PCB cleaned and re-saved with structural integrity intact.")
