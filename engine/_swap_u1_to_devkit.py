"""Surgical swap: U1 (SMD ESP32-S3-WROOM-1) → U1_Socket_L + U1_Socket_R (DevKitC-1).

Phases inside this script:
  1. Inspect current U1 padmap, then REMOVE U1 from the board.
  2. Detect footprints that would overlap the new DevKit area (auto-relocate them).
  3. Add two 1x22 pin header sockets via KiCad library footprint load.
  4. Assign nets per the user-approved DevKitC pin map.
  5. Save. (Track stitching for 6 signals handled in a follow-up script.)
"""
import sys
import math
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

# ── Geometry (horizontal orientation; pins run along X axis) ─────────────────
U1_CX, U1_CY = 94.0, 62.0
ROW_SEPARATION_MM = 25.4         # standard 1-inch DevKit spacing
PIN_PITCH_MM = 2.54
PIN_COUNT = 22
TOP_ROW_Y = U1_CY - ROW_SEPARATION_MM / 2.0    # 49.3 mm  (J1 / U1_Socket_L)
BOT_ROW_Y = U1_CY + ROW_SEPARATION_MM / 2.0    # 74.7 mm  (J3 / U1_Socket_R)
FIRST_PIN_X = U1_CX - (PIN_COUNT - 1) * PIN_PITCH_MM / 2.0    # 67.33 mm

# DevKit area for relocation check (with 1mm clearance margin)
DEVKIT_X_MIN = FIRST_PIN_X - 2.0
DEVKIT_X_MAX = FIRST_PIN_X + (PIN_COUNT - 1) * PIN_PITCH_MM + 2.0
DEVKIT_Y_MIN = TOP_ROW_Y - 2.0
DEVKIT_Y_MAX = BOT_ROW_Y + 2.0

# ── User-approved net-to-pin mapping ────────────────────────────────────────
# DevKitC-1 standard pin assignments (see Espressif schematic).
# Only pins carrying real signals are listed; rest are NC.
J1_NET_MAP = {           # Top row (U1_Socket_L)
    1:  "+3V3",
    2:  "+3V3",
    8:  "DWM_IRQ_3V3",        # IO15
    9:  "DWM_EXT_TX_3V3",     # IO16
    18: "SPI_CS_3V3_MCU",     # IO10
    19: "SPI_MOSI_3V3_MCU",   # IO11
    20: "SPI_CLK_3V3_MCU",    # IO12
    21: "SPI_MISO_3V3_MCU",   # IO13
}
J3_NET_MAP = {           # Bottom row (U1_Socket_R)
    1:  "GND",
    21: "GND",
    22: "GND",
}

board = pcbnew.LoadBoard(PCB)
print(f"[INFO] Loaded board: {len(list(board.GetFootprints()))} footprints")

# ── PHASE 1: Inspect & remove U1 ─────────────────────────────────────────────
u1 = next((fp for fp in board.GetFootprints() if fp.GetReference() == "U1"), None)
if u1 is None:
    raise SystemExit("[FATAL] U1 not on board (already swapped?)")
print(f"[PHASE 1] Removing U1 (SMD ESP32-S3-WROOM-1, {len(list(u1.Pads()))} pads)...")
board.Remove(u1)

# ── PHASE 2: Detect footprints overlapping DevKit area; relocate them ────────
def rect_overlaps_devkit(fp):
    bb = fp.GetBoundingBox()
    x_min = pcbnew.ToMM(bb.GetLeft())
    x_max = pcbnew.ToMM(bb.GetRight())
    y_min = pcbnew.ToMM(bb.GetTop())
    y_max = pcbnew.ToMM(bb.GetBottom())
    return not (x_max < DEVKIT_X_MIN or x_min > DEVKIT_X_MAX or
                y_max < DEVKIT_Y_MIN or y_min > DEVKIT_Y_MAX)

overlapping = [fp for fp in board.GetFootprints() if rect_overlaps_devkit(fp)]
print(f"[PHASE 2] {len(overlapping)} footprints overlap DevKit area "
      f"[X:{DEVKIT_X_MIN:.1f}..{DEVKIT_X_MAX:.1f}, Y:{DEVKIT_Y_MIN:.1f}..{DEVKIT_Y_MAX:.1f}]")

# Relocate each overlapping footprint to a nearby free spot, away from DevKit
# Strategy: push each one OUTWARD (away from board center (80, 50)) by some delta
BOARD_CX, BOARD_CY = 80.0, 50.0
SHIFT = 12.0  # mm
for fp in overlapping:
    p = fp.GetPosition()
    px = pcbnew.ToMM(p.x)
    py = pcbnew.ToMM(p.y)
    # vector away from DevKit center toward board edge
    dx = px - U1_CX
    dy = py - U1_CY
    norm = math.hypot(dx, dy) or 1.0
    new_px = px + (dx / norm) * SHIFT
    new_py = py + (dy / norm) * SHIFT
    # clamp inside board (rough: 5mm margin from 0/160 X and 0/100 Y)
    new_px = max(5.0, min(155.0, new_px))
    new_py = max(5.0, min(95.0, new_py))
    fp.SetPosition(pcbnew.VECTOR2I(int(pcbnew.FromMM(new_px)), int(pcbnew.FromMM(new_py))))
    print(f"  shifted {fp.GetReference():<8}  ({px:>6.2f},{py:>6.2f}) → ({new_px:>6.2f},{new_py:>6.2f})")

# ── PHASE 3: Add the two pin headers via KiCad library ───────────────────────
KICAD_FP_LIB = r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Connector_PinHeader_2.54mm.pretty"
FP_NAME = "PinHeader_1x22_P2.54mm_Vertical"

import os
if not os.path.exists(KICAD_FP_LIB):
    raise SystemExit(f"[FATAL] library not found: {KICAD_FP_LIB}")

print(f"[PHASE 3] Loading footprint {FP_NAME} from {KICAD_FP_LIB}...")

def add_header(ref, center_y, pin_net_map):
    # Direct function loads from a .pretty library; returns FOOTPRINT* or None
    fp = pcbnew.FootprintLoad(KICAD_FP_LIB, FP_NAME)
    if fp is None:
        raise SystemExit(f"[FATAL] could not load {FP_NAME}")
    # set position
    fp.SetPosition(pcbnew.VECTOR2I(
        int(pcbnew.FromMM(U1_CX)),
        int(pcbnew.FromMM(center_y))
    ))
    fp.SetReference(ref)
    fp.SetValue("1x22 Female Pin Header 2.54mm")
    board.Add(fp)
    # Assign nets per pin map; default = leave as no-net
    nets_db = board.GetNetsByName()
    assigned = 0
    for pad in fp.Pads():
        try:
            n = int(pad.GetNumber())
        except ValueError:
            continue
        if n in pin_net_map:
            net_name = pin_net_map[n]
            if net_name in nets_db:
                pad.SetNetCode(nets_db[net_name].GetNetCode())
                assigned += 1
            else:
                print(f"  [WARN] net '{net_name}' for {ref}.{n} not in board nets")
    print(f"  {ref}: added at Y={center_y:.2f} mm, {assigned} pin(s) net-assigned")
    return fp

j1 = add_header("U1_Socket_L", TOP_ROW_Y, J1_NET_MAP)
j3 = add_header("U1_Socket_R", BOT_ROW_Y, J3_NET_MAP)

# ── PHASE 4: Save ────────────────────────────────────────────────────────────
if not pcbnew.SaveBoard(PCB, board):
    raise SystemExit("[FATAL] SaveBoard failed")
print(f"[OK] PCB saved.")
print(f"[OK] U1_Socket_L pin 1 at ({FIRST_PIN_X:.2f}, {TOP_ROW_Y:.2f}) mm")
print(f"[OK] U1_Socket_R pin 1 at ({FIRST_PIN_X:.2f}, {BOT_ROW_Y:.2f}) mm")
