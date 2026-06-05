from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.netlist_source_normalizer import normalize_design_source


def _write_bom(path: Path) -> None:
    rows = [
        {
            "Item": "1",
            "Qty": "1",
            "Reference": "U1",
            "Value": "ESP32-S3-WROOM-2-N32R16",
            "Description": "WiFi + BLE MCU Module",
            "Manufacturer": "Espressif",
            "Part Number": "ESP32-S3-WROOM-2-N32R16",
            "Package / Footprint": "Module (plugs into SK1+SK2)",
            "Critical Placement Distance": "Centered on SK1+SK2 sockets",
            "Notes": "NOT soldered to PCB directly. Plugs into SK1+SK2 sockets.",
        },
        {
            "Item": "2",
            "Qty": "2",
            "Reference": "SK1-SK2",
            "Value": "PinSocket_1x22_P2.54mm",
            "Description": "2x22-pin Female Socket",
            "Manufacturer": "Wurth Elektronik",
            "Part Number": "61302211821",
            "Package / Footprint": "Connector_PinSocket_2.54mm:PinSocket_1x22_P2.54mm_Vertical",
            "Critical Placement Distance": "SK1 and SK2 parallel rows",
            "Notes": "GPIO33-37 pads MUST NOT be connected.",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        bom = Path(tmp) / "BOM.csv"
        _write_bom(bom)
        netlist = {
            "schema": "AI_Netlist_v1",
            "components": [
                {
                    "ref": "U1",
                    "type": "mcu",
                    "value": "ESP32-S3 module",
                    "manufacturer": "Espressif",
                    "part_number": "ESP32-S3-WROOM-2-N32R16",
                    "footprint": "RF_Module:ESP32-S3-WROOM-2",
                    "reason": "host",
                    "constraints": [],
                }
            ],
            "nets": [
                {
                    "net": "+3V3",
                    "pins": ["U1.3V3"],
                    "net_class": "power",
                    "reason": "rail",
                },
                {
                    "net": "SPI_CS_3V3",
                    "pins": ["U1.GPIO10"],
                    "net_class": "spi",
                    "reason": "spi",
                },
                {
                    "net": "IRQ_ALIAS",
                    "pins": ["SK1.Pin_GPIO14"],
                    "net_class": "gpio",
                    "reason": "ai socket alias",
                },
                {
                    "net": "RESERVED",
                    "pins": ["U1.GPIO36"],
                    "net_class": "gpio",
                    "reason": "must drop",
                },
            ],
        }
        normalized = normalize_design_source(netlist, bom)

    by_ref = {c["ref"]: c for c in normalized["components"]}
    failures = []

    def expect(name: str, condition: bool) -> None:
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(name)

    expect("U1 remains source-only", by_ref["U1"]["not_pcb_mounted"] is True)
    expect("U1 is virtual_module", by_ref["U1"]["type"] == "virtual_module")
    expect("SK1 added", by_ref["SK1"]["type"] == "socket")
    expect("SK2 added", by_ref["SK2"]["type"] == "socket")
    pins_by_net = {n["net"]: n["pins"] for n in normalized["nets"]}
    expect("+3V3 moved to SK1.2", pins_by_net["+3V3"] == ["SK1.2"])
    expect("GPIO10 moved to SK2.14", pins_by_net["SPI_CS_3V3"] == ["SK2.14"])
    expect("SK alias GPIO14 moved to SK2.10", pins_by_net["IRQ_ALIAS"] == ["SK2.10"])
    expect("reserved GPIO36 dropped", pins_by_net["RESERVED"] == [])

    return 1 if failures else 0


def test_grouped_bom_refs_are_expanded_without_concatenating_names() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        bom = Path(tmp) / "BOM.csv"
        rows = [
            {
                "Item": "1",
                "Qty": "5",
                "Reference": "R1-R3 R_LED4 R_LED5",
                "Value": "220R",
                "Description": "LED resistors",
                "Manufacturer": "Yageo",
                "Part Number": "RC0805FR-07220RL",
                "Package / Footprint": "0805",
                "Critical Placement Distance": "",
                "Notes": "",
            },
            {
                "Item": "2",
                "Qty": "1",
                "Reference": "U8",
                "Value": "TPL5010DDCR",
                "Description": "Watchdog timer",
                "Manufacturer": "Texas Instruments",
                "Part Number": "TPL5010DDCR",
                "Package / Footprint": "SOT-23-6",
                "Critical Placement Distance": "",
                "Notes": "",
            }
        ]
        with bom.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        netlist = {
            "schema": "AI_Netlist_v1",
            "components": [
                {
                    "ref": "R1-R3R_LED4R_LED5",
                    "type": "component",
                    "value": "220R",
                    "manufacturer": "Yageo",
                    "part_number": "RC0805FR-07220RL",
                    "footprint": "",
                }
            ],
            "nets": [],
        }
        normalized = normalize_design_source(netlist, bom)

    refs = {c["ref"] for c in normalized["components"]}
    by_ref = {c["ref"]: c for c in normalized["components"]}
    expected = {"R1", "R2", "R3", "R_LED4", "R_LED5"}
    failures = []

    def expect(name: str, condition: bool) -> None:
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}")
        if not condition:
            failures.append(name)

    expect("group refs expanded", expected <= refs)
    expect("concatenated fake ref absent", "R1-R3R_LED4R_LED5" not in refs)
    expect("package footprint promoted", by_ref["U8"]["footprint"] == "Package_TO_SOT_SMD:SOT-23-6")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main() or test_grouped_bom_refs_are_expanded_without_concatenating_names())
