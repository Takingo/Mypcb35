"""Emit a HITL blocker for the 4 overlapping components at decision-A area."""
import sys
sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
sys.path.insert(0, r"C:\Mypcb")
import pcbnew
from engine.hitl_manager import emit_blocker

PCB = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
OVERLAPS = ["MOV1", "U6", "J1", "U7"]
DEVKIT_BOX = {"x_min": 11.3, "y_min": 15.3, "x_max": 68.7, "y_max": 44.7}

board = pcbnew.LoadBoard(PCB)
ctx = {
    "previous_hitl_decision": "A: Place DevKit at top-left (40, 30), pins horizontal",
    "devkit_area_mm": DEVKIT_BOX,
    "board_size_mm": [160, 100],
    "overlapping_components": [],
    "next_step_after_resolution": "swap U1 SMD WROOM → 2x PinHeader_1x22 sockets at (40, 30) + GND/3V3 via zone fill + HITL signal routing blocker",
}
for fp in board.GetFootprints():
    ref = fp.GetReference()
    if ref in OVERLAPS:
        pos = fp.GetPosition()
        bb = fp.GetBoundingBox()
        ctx["overlapping_components"].append({
            "ref": ref,
            "value": fp.GetValue(),
            "footprint": fp.GetFPID().GetLibItemName().wx_str(),
            "current_position_mm": [round(pcbnew.ToMM(pos.x), 2),
                                     round(pcbnew.ToMM(pos.y), 2)],
            "bbox_mm": [round(pcbnew.ToMM(bb.GetWidth()), 2),
                        round(pcbnew.ToMM(bb.GetHeight()), 2)],
        })

state = emit_blocker(
    blocker_type="placement",
    question=(
        "Decision A (DevKit at top-left 40,30) requires 4 existing components "
        "to move out of X:11..68, Y:15..45. Where should MOV1, U6, J1, U7 go? "
        "Each move impacts AC mains routing (MOV1, J1), 5V supply (U6), and "
        "3V3 LDO (U7)."
    ),
    context=ctx,
    suggested_choices=[
        {
            "id": "A1",
            "label": "Move all 4 to far right edge (X>=130)",
            "consequence": "Frees DevKit area but creates dense right-side cluster; AC mains route lengthens",
        },
        {
            "id": "A2",
            "label": "Move only MOV1+J1 to right (X>=140), keep U6+U7 by shifting down (Y>=70)",
            "consequence": "Preserves AC mains short path on right; LDOs near low-V loads at bottom",
        },
        {
            "id": "A3",
            "label": "Swap to choice C: expand board to 175x100 (no relocations needed)",
            "consequence": "Breaks 160x100 enclosure fit but eliminates all relocation risk",
        },
        {
            "id": "A4",
            "label": "Revert decision A entirely; keep SMD WROOM (option D)",
            "consequence": "Production ZIP stays valid; DevKit conversion permanently shelved",
        },
    ],
)

print(f"\n[OK] Cascade blocker emitted. session_id={state['session_id']}")
print(f"     Engine pauses until assets/generated/hitl_answer.json appears.")
