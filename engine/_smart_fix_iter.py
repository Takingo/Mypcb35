"""Iteration: aggressive forward-fix of DevKit-swap DRC violations.

1. Rip every track on the 6 signal nets that I created in the swap (any straight
   F.Cu segment with both endpoints in the socket area).
2. Smarter relocation for R10/R11/R12/R13/K2: scan board on a 1mm grid for
   the nearest cell whose enlarged bbox doesn't intersect ANY other footprint
   courtyard or pad bbox.
3. Multi-segment Manhattan routing for the 6 signals with simple obstacle
   detection on F.Cu (drop a via to B.Cu when blocked, route on B.Cu, via back).
"""
import sys
import math
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

SIGNAL_NETS = ["DWM_IRQ_3V3", "DWM_EXT_TX_3V3",
               "SPI_CS_3V3_MCU", "SPI_MOSI_3V3_MCU",
               "SPI_CLK_3V3_MCU", "SPI_MISO_3V3_MCU"]
SOCKET_REFS = {"U1_Socket_L", "U1_Socket_R"}
RELOCATED = {"R10", "R11", "R12", "R13", "K2"}

TRACK_W_MM = 0.25
CLEARANCE_MM = 0.4
VIA_W_MM = 0.6
VIA_DRILL_MM = 0.3
BOARD_W, BOARD_H = 160.0, 100.0
MARGIN = 3.0


def mm(v: float) -> int:
    return int(pcbnew.FromMM(v))


def to_mm(v: int) -> float:
    return pcbnew.ToMM(v)


def fp_bbox_mm(fp):
    bb = fp.GetBoundingBox()
    return (to_mm(bb.GetLeft()), to_mm(bb.GetTop()),
            to_mm(bb.GetRight()), to_mm(bb.GetBottom()))


def rect_intersects(a, b, margin=0.0):
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return not (ax2 + margin < bx1 or ax1 - margin > bx2 or
                ay2 + margin < by1 or ay1 - margin > by2)


# ── Step 1: rip all F.Cu segments on the 6 signal nets whose endpoint is at a
#           socket pad position (i.e., tracks I added during the swap) ─────────
board = pcbnew.LoadBoard(PCB)
nets = board.GetNetsByName()
signal_codes = {nets[n].GetNetCode() for n in SIGNAL_NETS if n in nets}

socket_pad_positions = set()
for fp in board.GetFootprints():
    if fp.GetReference() in SOCKET_REFS:
        for pad in fp.Pads():
            p = pad.GetPosition()
            socket_pad_positions.add((round(to_mm(p.x), 2), round(to_mm(p.y), 2)))

to_remove = []
for t in list(board.GetTracks()):
    if isinstance(t, pcbnew.PCB_VIA):
        continue
    if t.GetNetCode() not in signal_codes:
        continue
    s, e = t.GetStart(), t.GetEnd()
    key_s = (round(to_mm(s.x), 2), round(to_mm(s.y), 2))
    key_e = (round(to_mm(e.x), 2), round(to_mm(e.y), 2))
    if key_s in socket_pad_positions or key_e in socket_pad_positions:
        to_remove.append(t)
for t in to_remove:
    board.Remove(t)
print(f"[STEP 1] Removed {len(to_remove)} stale signal track segment(s).")

pcbnew.SaveBoard(PCB, board)
board = pcbnew.LoadBoard(PCB)

# ── Step 2: smarter relocation of R10-R13, K2 ────────────────────────────────
# Compute occupied regions from all footprints EXCEPT the relocated ones.
fixed_boxes = []
relocated_fps = []
for fp in board.GetFootprints():
    if fp.GetReference() in RELOCATED:
        relocated_fps.append(fp)
        continue
    fixed_boxes.append(fp_bbox_mm(fp))

# For each relocated part, find nearest valid cell on a 1mm grid that
# (a) fits the part bbox with margin, (b) doesn't intersect any fixed_box
def find_free_spot(target_w, target_h, near_x, near_y, fixed):
    best = None
    best_d = 1e9
    # Spiral search radius 0..40mm in 1mm grid
    for r in range(0, 41):
        for ang in range(0, 360, 15):
            cx = near_x + r * math.cos(math.radians(ang))
            cy = near_y + r * math.sin(math.radians(ang))
            if cx < MARGIN + target_w/2 or cx > BOARD_W - MARGIN - target_w/2:
                continue
            if cy < MARGIN + target_h/2 or cy > BOARD_H - MARGIN - target_h/2:
                continue
            box = (cx - target_w/2, cy - target_h/2, cx + target_w/2, cy + target_h/2)
            collide = any(rect_intersects(box, fb, 0.5) for fb in fixed)
            if not collide:
                d = math.hypot(cx - near_x, cy - near_y)
                if d < best_d:
                    best_d = d
                    best = (cx, cy)
        if best is not None and r >= 5:
            return best
    return best

print(f"[STEP 2] Re-placing {len(relocated_fps)} relocated parts (smarter scan):")
for fp in relocated_fps:
    box = fp_bbox_mm(fp)
    w = box[2] - box[0]
    h = box[3] - box[1]
    cur_x = (box[0] + box[2]) / 2
    cur_y = (box[1] + box[3]) / 2
    # Try to find a spot near the current location
    spot = find_free_spot(w, h, cur_x, cur_y, fixed_boxes)
    if spot is None:
        print(f"  {fp.GetReference()}: NO FREE SPOT FOUND, leaving in place")
        continue
    nx, ny = spot
    fp.SetPosition(pcbnew.VECTOR2I(mm(nx), mm(ny)))
    # After placing, add this part's new bbox to fixed_boxes for next placements
    new_box = (nx - w/2, ny - h/2, nx + w/2, ny + h/2)
    fixed_boxes.append(new_box)
    print(f"  {fp.GetReference()}: ({cur_x:.1f},{cur_y:.1f}) → ({nx:.1f},{ny:.1f})  bbox {w:.1f}×{h:.1f}")

pcbnew.SaveBoard(PCB, board)
board = pcbnew.LoadBoard(PCB)
nets = board.GetNetsByName()

# ── Step 3: Manhattan routing with via-on-blocked for the 6 signal nets ──────
# For each signal, find:
#   - source: socket pin position
#   - target: nearest other pad on same net
# Route: try L-bend on F.Cu. If any segment intersects a footprint bbox (not
# endpoints), drop a via to B.Cu, route on B.Cu, via back near target.

def list_pads_on_net(net_name):
    code = nets[net_name].GetNetCode() if net_name in nets else None
    if code is None:
        return []
    out = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            if pad.GetNetCode() == code:
                p = pad.GetPosition()
                out.append((fp.GetReference(), pad.GetNumber(),
                            to_mm(p.x), to_mm(p.y)))
    return out


def segment_intersects_any_fp(x1, y1, x2, y2, exclude_refs):
    # Sample 20 points along segment, check if any falls inside a fixed bbox
    for i in range(1, 20):
        t = i / 20.0
        sx, sy = x1 + t * (x2 - x1), y1 + t * (y2 - y1)
        for fp in board.GetFootprints():
            if fp.GetReference() in exclude_refs:
                continue
            bb = fp.GetBoundingBox()
            if (to_mm(bb.GetLeft()) - 0.3 <= sx <= to_mm(bb.GetRight()) + 0.3 and
                to_mm(bb.GetTop()) - 0.3 <= sy <= to_mm(bb.GetBottom()) + 0.3):
                return True
    return False


def add_track(x1, y1, x2, y2, layer, netcode):
    t = pcbnew.PCB_TRACK(board)
    t.SetStart(pcbnew.VECTOR2I(mm(x1), mm(y1)))
    t.SetEnd(pcbnew.VECTOR2I(mm(x2), mm(y2)))
    t.SetLayer(layer)
    t.SetWidth(mm(TRACK_W_MM))
    t.SetNetCode(netcode)
    board.Add(t)


def add_via(x, y, netcode):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
    v.SetWidth(mm(VIA_W_MM))
    v.SetDrill(mm(VIA_DRILL_MM))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetNetCode(netcode)
    board.Add(v)


routed = 0
for net_name in SIGNAL_NETS:
    pads = list_pads_on_net(net_name)
    src = next((p for p in pads if p[0] in SOCKET_REFS), None)
    others = [p for p in pads if p[0] not in SOCKET_REFS]
    if src is None or not others:
        print(f"  [skip] {net_name}: no socket or no target")
        continue
    tgt = min(others, key=lambda p: math.hypot(p[2]-src[2], p[3]-src[3]))
    x1, y1 = src[2], src[3]
    x2, y2 = tgt[2], tgt[3]
    netcode = nets[net_name].GetNetCode()
    excl = {src[0], tgt[0]}
    # Try L-shape on F.Cu: go horizontal first, then vertical
    midx, midy = x2, y1  # corner at (x2, y1)
    seg1_blocked = segment_intersects_any_fp(x1, y1, midx, midy, excl)
    seg2_blocked = segment_intersects_any_fp(midx, midy, x2, y2, excl)
    if not seg1_blocked and not seg2_blocked:
        add_track(x1, y1, midx, midy, pcbnew.F_Cu, netcode)
        add_track(midx, midy, x2, y2, pcbnew.F_Cu, netcode)
        print(f"  {net_name}: L-route F.Cu OK   {src[0]}.{src[1]}→{tgt[0]}.{tgt[1]}")
        routed += 1
        continue
    # Try other L-shape: vertical first, then horizontal
    midx, midy = x1, y2
    seg1b = segment_intersects_any_fp(x1, y1, midx, midy, excl)
    seg2b = segment_intersects_any_fp(midx, midy, x2, y2, excl)
    if not seg1b and not seg2b:
        add_track(x1, y1, midx, midy, pcbnew.F_Cu, netcode)
        add_track(midx, midy, x2, y2, pcbnew.F_Cu, netcode)
        print(f"  {net_name}: L-route F.Cu (alt) {src[0]}.{src[1]}→{tgt[0]}.{tgt[1]}")
        routed += 1
        continue
    # Fall back: drop via near src, run on B.Cu, via back near tgt
    via1_x, via1_y = x1, y1 + 1.0 if y1 < y2 else y1 - 1.0
    via2_x, via2_y = x2, y2 + 1.0 if y1 < y2 else y2 - 1.0
    add_track(x1, y1, via1_x, via1_y, pcbnew.F_Cu, netcode)
    add_via(via1_x, via1_y, netcode)
    add_track(via1_x, via1_y, x2, via1_y, pcbnew.B_Cu, netcode)
    add_track(x2, via1_y, via2_x, via2_y, pcbnew.B_Cu, netcode)
    add_via(via2_x, via2_y, netcode)
    add_track(via2_x, via2_y, x2, y2, pcbnew.F_Cu, netcode)
    print(f"  {net_name}: VIA+B.Cu fallback     {src[0]}.{src[1]}→{tgt[0]}.{tgt[1]}")
    routed += 1

pcbnew.SaveBoard(PCB, board)
print(f"\n[OK] iteration complete: {routed} signal(s) routed; saved.")
