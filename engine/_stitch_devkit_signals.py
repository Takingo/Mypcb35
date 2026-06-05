"""Add F.Cu tracks from new socket signal pins to the nearest still-existing pad
on that same net, so DRC sees them as electrically connected.

GND and +3V3 will be auto-connected via zone fill (next step) — no track needed.
Only the 6 signal nets need an explicit track stitch."""
import sys
import math
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

SIGNAL_NETS = [
    "DWM_IRQ_3V3",
    "DWM_EXT_TX_3V3",
    "SPI_CS_3V3_MCU",
    "SPI_MOSI_3V3_MCU",
    "SPI_CLK_3V3_MCU",
    "SPI_MISO_3V3_MCU",
]

board = pcbnew.LoadBoard(PCB)
nets = board.GetNetsByName()

def all_pads_on_net(net_name):
    """Return list of (ref, padnum, x, y) for every pad with this net."""
    netcode = nets[net_name].GetNetCode() if net_name in nets else None
    if netcode is None:
        return []
    out = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == netcode:
                p = pad.GetPosition()
                out.append((fp.GetReference(), pad.GetNumber(),
                            pcbnew.ToMM(p.x), pcbnew.ToMM(p.y)))
    return out

stitch_count = 0
for net_name in SIGNAL_NETS:
    pads = all_pads_on_net(net_name)
    socket_pads = [p for p in pads if p[0] in ("U1_Socket_L", "U1_Socket_R")]
    other_pads = [p for p in pads if p[0] not in ("U1_Socket_L", "U1_Socket_R")]
    if not socket_pads or not other_pads:
        print(f"  [skip] {net_name}: socket={len(socket_pads)}, other={len(other_pads)}")
        continue
    src = socket_pads[0]   # socket pin
    # find nearest other pad
    best = min(other_pads, key=lambda p: math.hypot(p[2] - src[2], p[3] - src[3]))
    dist = math.hypot(best[2] - src[2], best[3] - src[3])
    # Add F.Cu track, width 0.25mm
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(int(pcbnew.FromMM(src[2])), int(pcbnew.FromMM(src[3]))))
    t.SetEnd(pcbnew.VECTOR2I(int(pcbnew.FromMM(best[2])), int(pcbnew.FromMM(best[3]))))
    t.SetLayer(pcbnew.F_Cu)
    t.SetWidth(int(pcbnew.FromMM(0.25)))
    t.SetNetCode(nets[net_name].GetNetCode())
    board.Add(t)
    stitch_count += 1
    print(f"  stitched {net_name:<22} {src[0]}.{src[1]} ({src[2]:.2f},{src[3]:.2f}) -> "
          f"{best[0]}.{best[1]} ({best[2]:.2f},{best[3]:.2f})  [{dist:.2f} mm]")

if not pcbnew.SaveBoard(PCB, board):
    raise SystemExit("[FATAL] SaveBoard failed")
print(f"\n[OK] {stitch_count} signal track(s) stitched and saved.")
