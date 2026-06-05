"""Re-fill all PCB zones so same-net copper islands get bridged by the polygon pour."""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

board = pcbnew.LoadBoard(PCB)
filler = pcbnew.ZONE_FILLER(board)
try:
    zones = [z for z in board.Zones()]
except TypeError:
    raw = board.Zones()
    zones = [raw.GetItem(i) for i in range(raw.Count())]

print(f"[INFO] Filling {len(zones)} zones...")
filler.Fill(zones)
pcbnew.SaveBoard(PCB, board)
print("[OK] Zones re-filled and saved.")
