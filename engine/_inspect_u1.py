"""Inspect U1's current pad-to-net mapping. Output JSON for the swap planner."""
import json
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
board = pcbnew.LoadBoard(PCB)

u1 = None
for fp in board.GetFootprints():
    if fp.GetReference() == "U1":
        u1 = fp
        break
if u1 is None:
    raise SystemExit("[FATAL] U1 not found")

pos = u1.GetPosition()
bbox = u1.GetBoundingBox()
print(f"=== U1 PHYSICAL ===")
print(f"  position:      ({pcbnew.ToMM(pos.x):.2f}, {pcbnew.ToMM(pos.y):.2f}) mm")
print(f"  bbox:          {pcbnew.ToMM(bbox.GetWidth()):.2f} x {pcbnew.ToMM(bbox.GetHeight()):.2f} mm")
print(f"  layer:         {'B.Cu' if u1.IsFlipped() else 'F.Cu'}")
print(f"  orientation:   {u1.GetOrientationDegrees():.1f}°")
print(f"  footprint:     {u1.GetFPID().GetLibItemName().wx_str()}")
print(f"  pad count:     {len(list(u1.Pads()))}")

print(f"\n=== U1 PAD → NET MAP ===")
pad_map = {}
for pad in u1.Pads():
    n = pad.GetNumber()
    net_name = pad.GetNetname()
    net_code = pad.GetNetCode()
    p = pad.GetPosition()
    pad_map[n] = {
        "net": net_name,
        "net_code": net_code,
        "x_mm": round(pcbnew.ToMM(p.x), 3),
        "y_mm": round(pcbnew.ToMM(p.y), 3),
    }

# Print sorted by pad number (as int if possible)
def pad_sort_key(k):
    try:
        return (0, int(k))
    except ValueError:
        return (1, k)

for n in sorted(pad_map.keys(), key=pad_sort_key):
    e = pad_map[n]
    print(f"  pad {n:>4}  net={e['net']:<30}  @ ({e['x_mm']:>7.2f}, {e['y_mm']:>7.2f})")

# Connected nets summary (non-empty)
nets_in_use = sorted({e["net"] for e in pad_map.values() if e["net"]})
print(f"\n=== U1 IS ON {len(nets_in_use)} DISTINCT NETS ===")
for net in nets_in_use:
    pads = [n for n, e in pad_map.items() if e["net"] == net]
    print(f"  {net:<30}  pads: {pads}")

# Save for the swap script
out = r"C:\Mypcb\engine\_u1_padmap.json"
with open(out, "w", encoding="utf-8") as f:
    json.dump({
        "footprint": u1.GetFPID().GetLibItemName().wx_str(),
        "position_mm": (round(pcbnew.ToMM(pos.x), 3), round(pcbnew.ToMM(pos.y), 3)),
        "orientation_deg": u1.GetOrientationDegrees(),
        "pad_count": len(pad_map),
        "pads": pad_map,
        "nets_in_use": nets_in_use,
    }, f, indent=2, ensure_ascii=False)
print(f"\n[OK] padmap saved to {out}")
