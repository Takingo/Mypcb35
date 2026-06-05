"""Run prune routine but with traceback exposed (no swallowing)."""
import sys
import traceback
from collections import defaultdict
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
board = pcbnew.LoadBoard(PCB)
copper_layers = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu]
grid = max(1, int(pcbnew.FromMM(0.05)))

def cell(x, y):
    return (int(round(x / grid)), int(round(y / grid)))

def neigh(c):
    cx, cy = c
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            yield (cx + dx, cy + dy)

try:
    print("STEP 1: zones")
    try:
        zones = [z for z in board.Zones()]
    except TypeError:
        raw = board.Zones()
        zones = [raw.GetItem(i) for i in range(raw.Count())] if hasattr(raw, "Count") else []
    print(f"  zones = {len(zones)}")

    print("STEP 2: pad cells")
    pad_layer_cells = defaultdict(set)
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            pos = pad.GetPosition()
            c = cell(pos.x, pos.y)
            net = pad.GetNetCode()
            ls = pad.GetLayerSet()
            for layer in copper_layers:
                try:
                    on = ls.Contains(layer)
                except Exception:
                    on = True
                if on:
                    pad_layer_cells[(layer, net)].add(c)
    print(f"  pad cells = {sum(len(v) for v in pad_layer_cells.values())}")

    print("STEP 3: connectivity")
    if hasattr(board, "BuildConnectivity"):
        board.BuildConnectivity()

    print("STEP 4: classify tracks vs vias")
    all_tracks = list(board.GetTracks())
    vias = [t for t in all_tracks if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in all_tracks if not isinstance(t, pcbnew.PCB_VIA)]
    print(f"  tracks={len(tracks)}  vias={len(vias)}")

    print("STEP 5: via cells")
    via_cells = defaultdict(set)
    for v in vias:
        p = v.GetPosition()
        via_cells[v.GetNetCode()].add(cell(p.x, p.y))
    print(f"  via cells captured")

    print("STEP 6: track endpoints")
    tend = defaultdict(int)
    segs_by_ln = defaultdict(list)
    for t in tracks:
        layer, net = t.GetLayer(), t.GetNetCode()
        a, b = t.GetStart(), t.GetEnd()
        for pt in (a, b):
            tend[(layer, net, cell(pt.x, pt.y))] += 1
        segs_by_ln[(layer, net)].append((id(t), a.x, a.y, b.x, b.y))
    print(f"  endpoints captured")

    print("STEP 7: try zone_hit on a sample via")
    if vias and zones:
        v = vias[0]
        p = v.GetPosition()
        net = v.GetNetCode()
        for layer in copper_layers:
            for z in zones:
                if z.GetNetCode() != net or not z.IsOnLayer(layer):
                    continue
                try:
                    hit = z.HitTestFilledArea(layer, p)
                    print(f"    zone hit layer={layer}: {hit}")
                except Exception as e:
                    print(f"    zone.HitTestFilledArea({layer}, p) FAILED: {type(e).__name__}: {e}")
                break
            break
    print("ALL STEPS COMPLETED OK")
except Exception as e:
    print(f"FAILURE: {type(e).__name__}: {e}")
    traceback.print_exc()
