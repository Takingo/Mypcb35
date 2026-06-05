"""Prune dangling copper. Save+reload between passes to avoid SWIG proxy invalidation."""
import sys
import traceback
from collections import defaultdict
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"


def prune_one_pass(board) -> int:
    """Returns number of removed items in this pass."""
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
        zones = [z for z in board.Zones()]
    except TypeError:
        raw = board.Zones()
        zones = [raw.GetItem(i) for i in range(raw.Count())] if hasattr(raw, "Count") else []

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

    def pad_hit(layer, net, c0):
        pc = pad_layer_cells.get((layer, net))
        return bool(pc) and any(c in pc for c in neigh(c0))

    def zone_hit(net, layer, pt):
        for z in zones:
            if z.GetNetCode() != net or not z.IsOnLayer(layer):
                continue
            try:
                if z.HitTestFilledArea(layer, pt):
                    return True
            except Exception:
                pass
        return False

    if hasattr(board, "BuildConnectivity"):
        board.BuildConnectivity()

    all_tracks = list(board.GetTracks())
    vias = [t for t in all_tracks if isinstance(t, pcbnew.PCB_VIA)]
    tracks = [t for t in all_tracks if not isinstance(t, pcbnew.PCB_VIA)]

    via_cells = defaultdict(set)
    for v in vias:
        p = v.GetPosition()
        via_cells[v.GetNetCode()].add(cell(p.x, p.y))

    tend = defaultdict(int)
    segs_by_ln = defaultdict(list)
    for t in tracks:
        layer, net = t.GetLayer(), t.GetNetCode()
        a, b = t.GetStart(), t.GetEnd()
        for pt in (a, b):
            tend[(layer, net, cell(pt.x, pt.y))] += 1
        segs_by_ln[(layer, net)].append((id(t), a.x, a.y, b.x, b.y))

    def on_other_seg(px, py, layer, net, self_id):
        tol2 = grid * grid
        for (sid, ax, ay, bx, by) in segs_by_ln.get((layer, net), ()):
            if sid == self_id:
                continue
            dx, dy = bx - ax, by - ay
            seg_len2 = dx * dx + dy * dy
            if seg_len2 == 0:
                if (px - ax) ** 2 + (py - ay) ** 2 <= tol2:
                    return True
                continue
            tparam = ((px - ax) * dx + (py - ay) * dy) / seg_len2
            tparam = max(0.0, min(1.0, tparam))
            cx, cy = ax + tparam * dx, ay + tparam * dy
            if (px - cx) ** 2 + (py - cy) ** 2 <= tol2:
                return True
        return False

    removed = 0

    for v in vias:
        p = v.GetPosition()
        net = v.GetNetCode()
        c0 = cell(p.x, p.y)
        layers_connected = 0
        for layer in copper_layers:
            track_here = any(tend.get((layer, net, c), 0) >= 1 for c in neigh(c0))
            if track_here or pad_hit(layer, net, c0) or zone_hit(net, layer, p):
                layers_connected += 1
        if layers_connected < 2:
            board.Remove(v)
            removed += 1

    for t in tracks:
        layer, net = t.GetLayer(), t.GetNetCode()
        self_id = id(t)
        dangling = False
        for pt in (t.GetStart(), t.GetEnd()):
            c0 = cell(pt.x, pt.y)
            others = sum(tend.get((layer, net, c), 0) for c in neigh(c0)) - 1
            via_here = any(c in via_cells.get(net, ()) for c in neigh(c0))
            if (others >= 1 or via_here or pad_hit(layer, net, c0)
                    or zone_hit(net, layer, pt)
                    or on_other_seg(pt.x, pt.y, layer, net, self_id)):
                continue
            dangling = True
            break
        if dangling:
            board.Remove(t)
            removed += 1

    return removed


try:
    total_removed = 0
    for pass_no in range(8):
        # Fresh load every pass — bypasses SWIG proxy invalidation across BuildConnectivity
        board = pcbnew.LoadBoard(PCB)
        all_tracks = list(board.GetTracks())
        vias = sum(1 for t in all_tracks if isinstance(t, pcbnew.PCB_VIA))
        tracks = len(all_tracks) - vias
        removed = prune_one_pass(board)
        total_removed += removed
        if removed > 0:
            pcbnew.SaveBoard(PCB, board)
        print(f"  pass {pass_no + 1}: {tracks} tracks + {vias} vias  →  removed {removed}")
        if removed == 0:
            break

    print(f"[OK] Total dangling items removed: {total_removed}")
except Exception:
    traceback.print_exc()
    sys.exit(1)
