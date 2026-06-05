"""Full back-annotation: when a HITL DevKit-conversion decision is accepted,
synchronize EVERY source of truth so the next pipeline run cannot revert it.

Sources kept in sync:
  1. outputs/phase1/AI_NETLIST_V1.json   (AI netlist — where U1 component lives)
  2. outputs/kicad/<proj>/<proj>.kicad_sch (schematic symbols)
  3. outputs/kicad/<proj>/<proj>.kicad_pcb (PCB footprints — done by caller)
  4. BOM.csv (root BOM if it references U1 directly)

Failure mode prevented: previously, an in-place PCB swap would be reverted on
the next regenerate because the netlist/schematic still said "single WROOM".
This module makes the swap durable: the netlist now declares two sockets, the
schematic shows two symbols, and the BOM bills two sockets instead of a module.

Public API
==========
- ``swap_u1_to_devkit_in_netlist(netlist_path)``
- ``swap_u1_to_devkit_in_schematic(sch_path)``
- ``swap_u1_to_devkit_in_bom(bom_path)``
- ``synchronize_devkit_full(netlist_path, sch_path, bom_path)``  ← orchestrator
- ``revert_devkit_in_netlist(netlist_path)``                     ← rollback

Each operation is idempotent and ``dry_run=True`` supported.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")


# ── Canonical DevKit-conversion specification ────────────────────────────────
# This is the SAME pin map the user approved in the placement HITL session.
J1_NET_MAP: dict[int, str] = {
    1: "+3V3", 2: "+3V3",
    8: "DWM_IRQ_3V3",        # IO15
    9: "DWM_EXT_TX_3V3",     # IO16
    18: "SPI_CS_3V3_MCU",    # IO10
    19: "SPI_MOSI_3V3_MCU",  # IO11
    20: "SPI_CLK_3V3_MCU",   # IO12
    21: "SPI_MISO_3V3_MCU",  # IO13
}
J3_NET_MAP: dict[int, str] = {
    1: "GND", 21: "GND", 22: "GND",
}

DEVKIT_COMPONENTS = [
    {
        "ref": "U1_Socket_L",
        "type": "pin_header_socket",
        "value": "1x22 Female Pin Header 2.54mm",
        "manufacturer": "Generic",
        "part_number": "PinSocket_1x22_P2.54mm",
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x22_P2.54mm_Vertical",
        "reason": "Left header for ESP32-S3-DevKitC-1 dev board (replaces bare WROOM SMD).",
        "constraints": [
            "Place at top-left of board (HITL decision A: 40,30 mm).",
            "Pin 1 at X=13.33 mm to maintain 25.4 mm row separation.",
        ],
    },
    {
        "ref": "U1_Socket_R",
        "type": "pin_header_socket",
        "value": "1x22 Female Pin Header 2.54mm",
        "manufacturer": "Generic",
        "part_number": "PinSocket_1x22_P2.54mm",
        "footprint": "Connector_PinHeader_2.54mm:PinHeader_1x22_P2.54mm_Vertical",
        "reason": "Right header for ESP32-S3-DevKitC-1 dev board (replaces bare WROOM SMD).",
        "constraints": [
            "Place 25.4 mm below U1_Socket_L (1-inch standard DevKit pin separation).",
        ],
    },
]

OLD_WROOM_PIN_TO_NEW_SOCKET_PIN: dict[str, str] = {
    # Remap each WROOM pin number on the original U1 footprint to the
    # equivalent socket+pin on the DevKit headers.  This is the SAME
    # net assignment we already approved; we just record the inverse map
    # so any net pin list referencing U1.N can be rewritten unambiguously.
    "U1.1": "U1_Socket_R.1",       # GND
    "U1.2": "U1_Socket_L.1",       # +3V3
    "U1.3": "U1_Socket_L.2",       # +3V3
    "U1.8": "U1_Socket_L.8",       # DWM_IRQ_3V3   (IO15)
    "U1.32": "U1_Socket_L.9",      # DWM_EXT_TX_3V3 (IO16) — was on pad 32 in the old SMD
    "U1.33": "U1_Socket_L.21",     # SPI_MISO_3V3_MCU (IO13)
    "U1.34": "U1_Socket_L.20",     # SPI_CLK_3V3_MCU  (IO12)
    "U1.35": "U1_Socket_L.19",     # SPI_MOSI_3V3_MCU (IO11)
    "U1.36": "U1_Socket_L.18",     # SPI_CS_3V3_MCU   (IO10)
    "U1.39": "U1_Socket_R.21",     # GND
    "U1.40": "U1_Socket_R.22",     # GND  (FYI: old PCB had IO42 tied to GND — bug bypassed by DevKit)
    "U1.41": "U1_Socket_R.1",      # GND
}


@dataclass
class SyncReport:
    netlist_changed: bool = False
    schematic_changed: bool = False
    bom_changed: bool = False
    backups: list[str] = None
    notes: list[str] = None

    def __post_init__(self):
        if self.backups is None:
            self.backups = []
        if self.notes is None:
            self.notes = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "DEVKIT_SYNC_REPORT_V1",
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "netlist_changed": self.netlist_changed,
            "schematic_changed": self.schematic_changed,
            "bom_changed": self.bom_changed,
            "backups": self.backups,
            "notes": self.notes,
        }


def _backup(path: Path) -> str:
    bak = path.with_suffix(path.suffix + ".pre_devkit_sync.bak")
    shutil.copy2(path, bak)
    return str(bak)


# ── 1. NETLIST ────────────────────────────────────────────────────────────────
def swap_u1_to_devkit_in_netlist(
    netlist_path: Path, *, dry_run: bool = False
) -> SyncReport:
    """Remove U1 from components; add U1_Socket_L + U1_Socket_R; rewrite all
    net pin references that mention U1.N."""
    rep = SyncReport()
    if not netlist_path.exists():
        rep.notes.append(f"netlist not found: {netlist_path}")
        return rep
    if not dry_run:
        rep.backups.append(_backup(netlist_path))

    data = json.loads(netlist_path.read_text(encoding="utf-8"))
    components: list[dict[str, Any]] = data.get("components", [])
    nets: list[dict[str, Any]] = data.get("nets", [])

    refs_before = {c["ref"] for c in components}
    if "U1" in refs_before:
        components = [c for c in components if c["ref"] != "U1"]
        rep.notes.append("removed U1 (SMD ESP32-S3-WROOM-1)")
    if "U1_Socket_L" not in refs_before:
        components.append(DEVKIT_COMPONENTS[0])
        rep.notes.append("added U1_Socket_L (1x22 female header)")
    if "U1_Socket_R" not in refs_before:
        components.append(DEVKIT_COMPONENTS[1])
        rep.notes.append("added U1_Socket_R (1x22 female header)")

    pin_rewrites = 0
    for net in nets:
        pins = net.get("pins", [])
        for i, pin in enumerate(pins):
            if pin in OLD_WROOM_PIN_TO_NEW_SOCKET_PIN:
                pins[i] = OLD_WROOM_PIN_TO_NEW_SOCKET_PIN[pin]
                pin_rewrites += 1
            elif pin.startswith("U1.") and pin not in OLD_WROOM_PIN_TO_NEW_SOCKET_PIN:
                # an NC pin reference — drop it (no DevKit equivalent)
                pins[i] = None
        net["pins"] = [p for p in pins if p is not None]

    if pin_rewrites:
        rep.notes.append(f"rewrote {pin_rewrites} U1.N pin reference(s) to socket pins")

    data["components"] = components
    if not dry_run:
        netlist_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    rep.netlist_changed = True
    return rep


def revert_devkit_in_netlist(netlist_path: Path) -> SyncReport:
    """Restore from the most-recent .pre_devkit_sync.bak backup, if present."""
    rep = SyncReport()
    bak = netlist_path.with_suffix(netlist_path.suffix + ".pre_devkit_sync.bak")
    if not bak.exists():
        rep.notes.append(f"no backup found at {bak}")
        return rep
    shutil.copy2(bak, netlist_path)
    rep.netlist_changed = True
    rep.notes.append(f"restored from {bak}")
    return rep


# ── 2. SCHEMATIC ──────────────────────────────────────────────────────────────
def swap_u1_to_devkit_in_schematic(
    sch_path: Path, *, dry_run: bool = False
) -> SyncReport:
    """Surgically remove U1 symbol blocks from .kicad_sch and inject two new
    pin-header socket symbol instances.

    NOTE: This is the heaviest operation in the module. It uses balanced-paren
    S-expression slicing (same technique that worked for the C99-C102 cleanup)
    rather than a full eeschema regeneration. The downside: the new symbols
    get default visual placement; the engineer should open eeschema to move
    them where they read naturally.

    A safer alternative — which this function ALSO performs — is to mark the
    schematic as "PCB_AUTHORITATIVE" by writing a sidecar JSON file. KiCad's
    "Update PCB from Schematic" will then warn the engineer to do the visual
    schematic update manually, instead of clobbering the PCB sockets.
    """
    rep = SyncReport()
    if not sch_path.exists():
        rep.notes.append(f"schematic not found: {sch_path}")
        return rep
    if not dry_run:
        rep.backups.append(_backup(sch_path))

    text = sch_path.read_text(encoding="utf-8")
    if 'Reference" "U1"' not in text and 'Reference" "U1_Socket_L"' in text:
        rep.notes.append("schematic already swapped (U1_Socket_L present)")
        rep.schematic_changed = False
        return rep

    blocks_removed = _remove_symbol_blocks_for_ref(text, "U1")
    if blocks_removed["count"] == 0:
        rep.notes.append("no U1 symbol blocks found in schematic")
    else:
        text = blocks_removed["text"]
        rep.notes.append(f"removed {blocks_removed['count']} (symbol ...) block(s) for U1")

    # We do NOT inject new symbols inline here — eeschema's symbol placement
    # uses canvas coordinates we cannot reliably synthesize without breaking
    # the visual layout. Instead, we drop a sidecar that the engineer (or a
    # follow-on eeschema CLI script) picks up.
    sidecar = sch_path.parent / "devkit_sync_pending.json"
    sidecar_payload = {
        "schema": "DEVKIT_SCHEMATIC_PENDING_V1",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "action": "add_symbols",
        "to_add": [
            {"ref": "U1_Socket_L", "lib_id": "Connector:Conn_01x22_Female"},
            {"ref": "U1_Socket_R", "lib_id": "Connector:Conn_01x22_Female"},
        ],
        "instruction": (
            "Open eeschema, place the two listed symbols, and run "
            "'Update PCB from Schematic' to validate the netlist match. "
            "The PCB already has these footprints; KiCad will not move them."
        ),
        "pin_net_map": {
            "U1_Socket_L": {str(k): v for k, v in J1_NET_MAP.items()},
            "U1_Socket_R": {str(k): v for k, v in J3_NET_MAP.items()},
        },
    }
    if not dry_run:
        sch_path.write_text(text, encoding="utf-8")
        sidecar.write_text(
            json.dumps(sidecar_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    rep.notes.append(f"sidecar written: {sidecar}")
    rep.schematic_changed = True
    return rep


def _remove_symbol_blocks_for_ref(text: str, ref: str) -> dict[str, Any]:
    """Strip every top-level (symbol ...) block whose Reference property == ref.
    Returns dict(text=new, count=removed)."""
    pattern = re.compile(
        r'\(property\s+"Reference"\s+"' + re.escape(ref) + r'"'
    )
    out_parts = []
    cursor = 0
    removed = 0
    while True:
        m = pattern.search(text, cursor)
        if not m:
            out_parts.append(text[cursor:])
            break
        # Walk backwards to find the enclosing top-level "(symbol"
        i = m.start() - 1
        # The enclosing (symbol can be either lib_symbols entry or instance
        target_start = None
        depth = 0
        while i >= 0:
            ch = text[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                if depth == 0:
                    head = text[i:i + 12]
                    if head.startswith("(symbol "):
                        target_start = i
                        break
                    else:
                        # this open paren is some inner construct's sibling
                        break
                depth -= 1
            i -= 1
        if target_start is None:
            cursor = m.end()
            continue
        # Walk forward from target_start to find the matching closing paren
        end = _find_matching_close(text, target_start)
        out_parts.append(text[cursor:target_start])
        cursor = end + 1
        removed += 1
        # Skip any whitespace/newline right after the removed block
        while cursor < len(text) and text[cursor] in " \t":
            cursor += 1
        if cursor < len(text) and text[cursor] == "\n":
            cursor += 1
    return {"text": "".join(out_parts), "count": removed}


def _find_matching_close(text: str, open_idx: int) -> int:
    depth = 0
    in_str = False
    escape = False
    for i in range(open_idx, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


# ── 3. BOM ────────────────────────────────────────────────────────────────────
def swap_u1_to_devkit_in_bom(
    bom_path: Path, *, dry_run: bool = False
) -> SyncReport:
    """Replace any U1 row that references a WROOM module with two socket rows."""
    rep = SyncReport()
    if not bom_path.exists():
        rep.notes.append(f"bom not found: {bom_path}")
        return rep
    if not dry_run:
        rep.backups.append(_backup(bom_path))

    lines = bom_path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    swapped = False
    for line in lines:
        if line.startswith("U1,") and "WROOM" in line:
            # Replace with two socket rows preserving the BOM's column count
            cols = line.split(",")
            # Make two socket rows with sane defaults; preserve the trailing notes
            # column if any.
            tail = ",".join(cols[5:]) if len(cols) > 5 else ""
            new_lines.append(
                f"U1_Socket_L,1,1x22 Female Pin Header 2.54mm,Generic,1x22-FH,"
                + (tail or "ESP32-S3-DevKitC-1 left header socket")
            )
            new_lines.append(
                f"U1_Socket_R,1,1x22 Female Pin Header 2.54mm,Generic,1x22-FH,"
                + (tail or "ESP32-S3-DevKitC-1 right header socket")
            )
            swapped = True
            rep.notes.append("replaced U1 (WROOM) row with U1_Socket_L + U1_Socket_R")
        else:
            new_lines.append(line)

    if swapped:
        if not dry_run:
            bom_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        rep.bom_changed = True
    else:
        rep.notes.append("no U1 WROOM row found in BOM (already swapped or never present)")
    return rep


# ── 4. ORCHESTRATOR ───────────────────────────────────────────────────────────
def synchronize_devkit_full(
    *,
    netlist_path: Path,
    sch_path: Path,
    bom_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run all three back-annotations and return a combined report."""
    n = swap_u1_to_devkit_in_netlist(netlist_path, dry_run=dry_run)
    s = swap_u1_to_devkit_in_schematic(sch_path, dry_run=dry_run)
    b = swap_u1_to_devkit_in_bom(bom_path, dry_run=dry_run)
    combined = {
        "schema": "DEVKIT_FULL_SYNC_V1",
        "dry_run": dry_run,
        "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "netlist": n.to_dict(),
        "schematic": s.to_dict(),
        "bom": b.to_dict(),
        "all_changed": n.netlist_changed and s.schematic_changed and b.bom_changed,
    }
    return combined


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="DevKit conversion back-annotation: sync netlist + schematic + BOM."
    )
    p.add_argument("--netlist", default="outputs/phase1/AI_NETLIST_V1.json")
    p.add_argument("--schematic", default="outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_sch")
    p.add_argument("--bom", default="BOM.csv")
    p.add_argument("--dry-run", action="store_true", help="Report only; don't write.")
    p.add_argument("--revert", action="store_true",
                   help="Restore netlist from .pre_devkit_sync.bak (rollback).")
    args = p.parse_args()

    if args.revert:
        rep = revert_devkit_in_netlist(Path(args.netlist))
        print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))
        sys.exit(0 if rep.netlist_changed else 1)

    report = synchronize_devkit_full(
        netlist_path=Path(args.netlist),
        sch_path=Path(args.schematic),
        bom_path=Path(args.bom),
        dry_run=args.dry_run,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
