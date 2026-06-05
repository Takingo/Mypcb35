"""Rotate DevKit sockets 90° so pins run horizontally; reposition; re-stitch.
Also: delete the 6 stale F.Cu signal tracks created by the previous stitch."""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

U1_CX, U1_CY = 94.0, 62.0
ROW_SEP = 25.4
PIN_PITCH = 2.54
PIN_COUNT = 22

TOP_ROW_Y = U1_CY - ROW_SEP / 2.0
BOT_ROW_Y = U1_CY + ROW_SEP / 2.0
# To make pins span 67.33..120.67 horizontally, place pin 1 of each header
# at (67.33, row_y).  Default footprint has pin 1 at origin and pins extend +Y.
# Rotating -90° (i.e. 270° in pcbnew API) flips +Y direction to +X direction.
TARGET_PIN1_X = U1_CX - (PIN_COUNT - 1) * PIN_PITCH / 2.0   # 67.33

SIGNAL_NETS = [
    "DWM_IRQ_3V3",
    "DWM_EXT_TX_3V3",
    "SPI_CS_3V3_MCU",
    "SPI_MOSI_3V3_MCU",
    "SPI_CLK_3V3_MCU",
    "SPI_MISO_3V3_MCU",
]
SOCKET_REFS = {"U1_Socket_L", "U1_Socket_R"}

board = pcbnew.LoadBoard(PCB)
nets = board.GetNetsByName()
signal_netcodes = {nets[n].GetNetCode() for n in SIGNAL_NETS if n in nets}

# ── 1. Delete the 6 stale signal tracks from previous stitch ─────────────────
to_remove = []
for t in list(board.GetTracks()):
    if isinstance(t, pcbnew.PCB_VIA):
        continue
    if t.GetNetCode() not in signal_netcodes:
        continue
    s, e = t.GetStart(), t.GetEnd()
    sx, ex = pcbnew.ToMM(s.x), pcbnew.ToMM(e.x)
    if abs(sx - 94.0) < 0.01 or abs(ex - 94.0) < 0.01:
        to_remove.append(t)
for t in to_remove:
    board.Remove(t)
removed_tracks = len(to_remove)
print(f"[INFO] Removed {removed_tracks} stale signal stitch track(s).")

# Save+reload to avoid SWIG proxy invalidation after Remove()
pcbnew.SaveBoard(PCB, board)
board = pcbnew.LoadBoard(PCB)

# ── 2. Rotate + reposition the two sockets ───────────────────────────────────
for fp in board.GetFootprints():
    ref = fp.GetReference()
    if ref not in SOCKET_REFS:
        continue
    # 90° rotation extends pins in +X direction (KiCad Y-inverted convention)
    fp.SetOrientationDegrees(90.0)
    # reposition so pin 1 lands at (67.33, row_y)
    row_y = TOP_ROW_Y if ref == "U1_Socket_L" else BOT_ROW_Y
    fp.SetPosition(pcbnew.VECTOR2I(
        int(pcbnew.FromMM(TARGET_PIN1_X)),
        int(pcbnew.FromMM(row_y)),
    ))
    # confirm pin1 + pin22 positions
    pads = sorted(fp.Pads(), key=lambda p: int(p.GetNumber()) if p.GetNumber().isdigit() else 99)
    if pads:
        p1 = pads[0].GetPosition()
        p22 = pads[-1].GetPosition()
        print(f"  {ref}: pin1=({pcbnew.ToMM(p1.x):.2f},{pcbnew.ToMM(p1.y):.2f}) "
              f"pin22=({pcbnew.ToMM(p22.x):.2f},{pcbnew.ToMM(p22.y):.2f})")

# Save the rotation so subsequent pad-position queries return new coords
pcbnew.SaveBoard(PCB, board)
print("[OK] sockets rotated + repositioned + saved.")
