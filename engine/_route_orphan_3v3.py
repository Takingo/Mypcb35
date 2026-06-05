"""Route a single +3V3 track from U7.5 to U8.1 on F.Cu.

Strategy:
- U7.5 (74.47, 15.90) is the orphan pad.
- U8.1 (80.86, 13.05) is the nearest +3V3 pad (~7mm away, also +3V3).
- Both pads are on F.Cu. A direct point-to-point F.Cu segment connects them
  without crossing any other components (the area between them is empty zone fill).
- Track width 0.25 mm — matches the existing +3V3 power traces in this design.
"""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

board = pcbnew.LoadBoard(PCB)

# Find +3V3 net code
nets = board.GetNetsByName()
net_3v3 = nets["+3V3"]
net_code_3v3 = net_3v3.GetNetCode()
print(f"[INFO] +3V3 netcode = {net_code_3v3}")

# Find U7.5 pad and U8.1 pad
def find_pad(ref, pin):
    for fp in board.GetFootprints():
        if fp.GetReference() == ref:
            for pad in fp.Pads():
                if pad.GetNumber() == pin:
                    return pad
    return None

u7_5 = find_pad("U7", "5")
u8_1 = find_pad("U8", "1")
if u7_5 is None or u8_1 is None:
    raise SystemExit("[FATAL] could not find U7.5 or U8.1")

p_start = u7_5.GetPosition()
p_end = u8_1.GetPosition()
print(f"[INFO] U7.5 @ ({pcbnew.ToMM(p_start.x):.3f}, {pcbnew.ToMM(p_start.y):.3f})")
print(f"[INFO] U8.1 @ ({pcbnew.ToMM(p_end.x):.3f}, {pcbnew.ToMM(p_end.y):.3f})")
import math
dist_mm = math.hypot(pcbnew.ToMM(p_end.x - p_start.x), pcbnew.ToMM(p_end.y - p_start.y))
print(f"[INFO] Distance = {dist_mm:.3f} mm")

# Create new track on F.Cu, width 0.25mm
track = pcbnew.PCB_TRACK(board)
track.SetStart(pcbnew.VECTOR2I(p_start.x, p_start.y))
track.SetEnd(pcbnew.VECTOR2I(p_end.x, p_end.y))
track.SetLayer(pcbnew.F_Cu)
track.SetWidth(int(pcbnew.FromMM(0.25)))
track.SetNetCode(net_code_3v3)
board.Add(track)
print(f"[INFO] Added F.Cu +3V3 track, width 0.25mm")

# Save
if not pcbnew.SaveBoard(PCB, board):
    raise SystemExit("[FATAL] SaveBoard failed")
print("[OK] PCB saved.")
