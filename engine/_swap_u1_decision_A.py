"""DevKit conversion per HITL Decision A: place sockets at top-left (40, 30).

Lessons learned from the previous attempt:
1. Do the swap mechanically (remove U1, add 2x sockets at (40,30) horizontal).
2. Connect ONLY GND + 3V3 via zone fill (these always work).
3. For the 6 signal nets, DO NOT auto-route. Instead emit a NEW HITL blocker
   asking the engineer how to route them (which layer, via drops, etc.).
4. Do NOT auto-relocate neighbors blindly — at (40, 30) the area should be
   clear; only relocate if a real overlap is detected.
5. After a SUCCESSFUL PCB swap, call engine.devkit_sync.synchronize_devkit_full
   so the netlist, schematic, and BOM ALL adopt the DevKit form. Without
   this, the next regenerate run reverts the PCB back to a WROOM SMD.
"""
import sys
from pathlib import Path
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
sys.path.insert(0, r"C:\Mypcb")
import pcbnew

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"

# HITL Decision A: top-left corner, horizontal pins
SOCKET_CENTER_X = 40.0
SOCKET_CENTER_Y = 30.0
ROW_SEP = 25.4              # 1-inch standard DevKit
PIN_PITCH = 2.54
PIN_COUNT = 22
TOP_ROW_Y = SOCKET_CENTER_Y - ROW_SEP / 2.0    # 17.3
BOT_ROW_Y = SOCKET_CENTER_Y + ROW_SEP / 2.0    # 42.7
PIN1_X = SOCKET_CENTER_X - (PIN_COUNT - 1) * PIN_PITCH / 2.0   # 13.33

# User-approved net→DevKit-pin mapping (from earlier session)
J1_NET_MAP = {  # top row, U1_Socket_L
    1: "+3V3", 2: "+3V3",
    8: "DWM_IRQ_3V3",       # IO15
    9: "DWM_EXT_TX_3V3",    # IO16
    18: "SPI_CS_3V3_MCU",   # IO10
    19: "SPI_MOSI_3V3_MCU", # IO11
    20: "SPI_CLK_3V3_MCU",  # IO12
    21: "SPI_MISO_3V3_MCU", # IO13
}
J3_NET_MAP = {  # bottom row, U1_Socket_R
    1: "GND", 21: "GND", 22: "GND",
}

KICAD_FP_LIB = r"C:\Program Files\KiCad\10.0\share\kicad\footprints\Connector_PinHeader_2.54mm.pretty"
FP_NAME = "PinHeader_1x22_P2.54mm_Vertical"


def to_mm(v):
    return pcbnew.ToMM(v)


def mm(v):
    return int(pcbnew.FromMM(v))


def fp_bbox_mm(fp):
    bb = fp.GetBoundingBox()
    return (to_mm(bb.GetLeft()), to_mm(bb.GetTop()),
            to_mm(bb.GetRight()), to_mm(bb.GetBottom()))


def rect_intersects(a, b, margin=0.5):
    return not (a[2] + margin < b[0] or a[0] - margin > b[2] or
                a[3] + margin < b[1] or a[1] - margin > b[3])


board = pcbnew.LoadBoard(PCB)
print(f"[INFO] Loaded {len(list(board.GetFootprints()))} footprints")

# Step 1: remove U1 SMD WROOM
u1 = next((fp for fp in board.GetFootprints() if fp.GetReference() == "U1"), None)
if u1 is None:
    print("[INFO] U1 not present (already swapped?)")
else:
    print(f"[STEP 1] Removing U1 SMD (62 pads)...")
    board.Remove(u1)

# Step 2: check decision-A area (X:11..70, Y:13.5..46.5) for overlaps
DEVKIT_BOX = (PIN1_X - 2.0, TOP_ROW_Y - 2.0,
              PIN1_X + (PIN_COUNT - 1) * PIN_PITCH + 2.0, BOT_ROW_Y + 2.0)
print(f"[STEP 2] DevKit area: X={DEVKIT_BOX[0]:.1f}..{DEVKIT_BOX[2]:.1f}, "
      f"Y={DEVKIT_BOX[1]:.1f}..{DEVKIT_BOX[3]:.1f}")
overlaps = []
for fp in board.GetFootprints():
    if rect_intersects(fp_bbox_mm(fp), DEVKIT_BOX, margin=0.5):
        overlaps.append(fp.GetReference())
if overlaps:
    print(f"[STEP 2] {len(overlaps)} component(s) overlap DevKit area at (40,30):")
    for r in overlaps:
        print(f"    - {r}")
    print("[STEP 2] Will NOT auto-relocate; emitting HITL blocker for each.")
else:
    print(f"[STEP 2] Area at (40,30) is CLEAR — no overlaps.")

# Step 3: add the two pin headers (only if no blocking overlaps)
if not overlaps:
    def add_header(ref, center_y, pin_map):
        fp = pcbnew.FootprintLoad(KICAD_FP_LIB, FP_NAME)
        if fp is None:
            raise SystemExit(f"[FATAL] could not load {FP_NAME}")
        fp.SetReference(ref)
        fp.SetValue("1x22 Female Pin Header 2.54mm")
        fp.SetOrientationDegrees(90.0)   # pins extend +X
        fp.SetPosition(pcbnew.VECTOR2I(mm(PIN1_X), mm(center_y)))
        board.Add(fp)
        nets_db = board.GetNetsByName()
        assigned = 0
        for pad in fp.Pads():
            try:
                n = int(pad.GetNumber())
            except ValueError:
                continue
            if n in pin_map and pin_map[n] in nets_db:
                pad.SetNetCode(nets_db[pin_map[n]].GetNetCode())
                assigned += 1
        print(f"  {ref}: at Y={center_y:.2f}, {assigned} pin(s) net-assigned")
        return fp

    add_header("U1_Socket_L", TOP_ROW_Y, J1_NET_MAP)
    add_header("U1_Socket_R", BOT_ROW_Y, J3_NET_MAP)
    print(f"[STEP 3] Pin1 at ({PIN1_X:.2f}, {TOP_ROW_Y:.2f}/{BOT_ROW_Y:.2f})  "
          f"Pin22 at ({PIN1_X + (PIN_COUNT-1)*PIN_PITCH:.2f}, ...)")
    pcbnew.SaveBoard(PCB, board)
    print("[OK] PCB Saved.")

    # ── STEP 4: SYNCHRONIZE netlist + schematic + BOM so this never reverts ──
    from engine.devkit_sync import synchronize_devkit_full
    import json
    sync = synchronize_devkit_full(
        netlist_path=Path("outputs/phase1/AI_NETLIST_V1.json"),
        sch_path=Path(PCB).with_suffix(".kicad_sch"),
        bom_path=Path("BOM.csv"),
        dry_run=False,
    )
    print("[STEP 4] Back-annotation results:")
    print(json.dumps(sync, indent=2, ensure_ascii=False))
    if not sync["all_changed"]:
        print("[WARN] Not all sources synchronized. Next regenerate may revert PCB.")
else:
    print("[STEP 3] SKIPPED — overlaps must be resolved first. PCB restored.")
    print("[STEP 4] SKIPPED — back-annotation only runs after a successful PCB swap.")
    # Don't save changes
