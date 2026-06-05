"""Inspect and repair the orphan +3V3 connection between U7.5 and the orphan via."""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

board = pcbnew.LoadBoard(PCB)

# Find the +3V3 net
net_3v3 = None
nets = board.GetNetsByName()
for name in ("+3V3", "+3.3V", "+3v3"):
    if name in nets:
        net_3v3 = nets[name]
        print(f"[INFO] Found net '{name}' netcode={net_3v3.GetNetCode()}")
        break

if net_3v3 is None:
    # list all nets containing 3V or 3.3
    all_names = [str(k) for k in nets.keys()]
    print(f"[WARN] No +3V3 net. All net names: {sorted(all_names)[:30]}")
    sys.exit(1)

net_code = net_3v3.GetNetCode()

# Catalog all pads on this net
print("\n[INFO] Pads on +3V3 net:")
for fp in board.GetFootprints():
    for pad in fp.Pads():
        if pad.GetNetCode() == net_code:
            p = pad.GetPosition()
            print(f"  {fp.GetReference()}.{pad.GetNumber()}  @  ({pcbnew.ToMM(p.x):.2f}, {pcbnew.ToMM(p.y):.2f})")

# Catalog all vias on this net
print("\n[INFO] Vias on +3V3 net:")
for t in board.GetTracks():
    if isinstance(t, pcbnew.PCB_VIA) and t.GetNetCode() == net_code:
        p = t.GetPosition()
        print(f"  via @ ({pcbnew.ToMM(p.x):.2f}, {pcbnew.ToMM(p.y):.2f})")

# Catalog all tracks on this net
print("\n[INFO] Tracks on +3V3 net:")
count = 0
for t in board.GetTracks():
    if not isinstance(t, pcbnew.PCB_VIA) and t.GetNetCode() == net_code:
        a = t.GetStart()
        b = t.GetEnd()
        layer = t.GetLayer()
        print(f"  track layer={layer}  ({pcbnew.ToMM(a.x):.2f},{pcbnew.ToMM(a.y):.2f}) → ({pcbnew.ToMM(b.x):.2f},{pcbnew.ToMM(b.y):.2f})")
        count += 1
        if count > 30:
            print("  ...")
            break
