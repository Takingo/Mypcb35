from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.input_evidence_validator import InputEvidenceValidator, expand_refs


class InputEvidenceValidatorTest(unittest.TestCase):
    def test_expand_refs_handles_ranges_and_space_separated_groups(self):
        self.assertEqual(
            expand_refs("R1-R3 R_LED4 R_LED5"),
            ["R1", "R2", "R3", "R_LED4", "R_LED5"],
        )
        self.assertEqual(expand_refs("SK1-SK2"), ["SK1", "SK2"])

    def test_bom_section_headers_and_present_grouped_refs_are_not_reported_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_bom(root / "BOM.csv")
            netlist_path = root / "outputs" / "phase1" / "AI_NETLIST_V1.json"
            netlist_path.parent.mkdir(parents=True)
            netlist_path.write_text(
                json.dumps(
                    {
                        "schema": "AI_Netlist_v1",
                        "components": [
                            {
                                "ref": ref,
                                "type": "passive",
                                "value": "220R",
                                "manufacturer": "Yageo",
                                "part_number": "RC0805FR-07220RL",
                                "footprint": "R_0805",
                            }
                            for ref in ["R1", "R2", "R3", "R_LED4", "R_LED5"]
                        ],
                        "nets": [{"net": "GND", "pins": ["R1.1"]}],
                    }
                ),
                encoding="utf-8",
            )

            report = InputEvidenceValidator(root).validate()

        ids = {finding["id"] for finding in report["findings"]}
        self.assertNotIn("BOM_ONLY_== PASSIVE - RESISTORS ==", ids)
        self.assertNotIn("BOM_ONLY_R1-R3 R_LED4 R_LED5", ids)
        self.assertFalse(any(item.startswith("NL_ONLY_R") for item in ids))
        self.assertEqual(report["counts"]["review"], 0)

    def test_j1_ac_bom_entry_accepts_j1_netlist_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_j1_alias_bom(root / "BOM.csv")
            netlist_path = root / "outputs" / "phase1" / "AI_NETLIST_V1.json"
            netlist_path.parent.mkdir(parents=True)
            netlist_path.write_text(
                json.dumps(
                    {
                        "schema": "AI_Netlist_v1",
                        "components": [
                            {
                                "ref": "J1",
                                "type": "connector",
                                "value": "AC Mains 3-pin",
                                "manufacturer": "Phoenix Contact",
                                "part_number": "1803578",
                                "footprint": "TerminalBlock",
                            }
                        ],
                        "nets": [{"net": "GND", "pins": ["J1.PE"]}],
                    }
                ),
                encoding="utf-8",
            )

            report = InputEvidenceValidator(root).validate()

        ids = {finding["id"] for finding in report["findings"]}
        self.assertNotIn("BOM_ONLY_J1_AC", ids)
        self.assertNotIn("NL_ONLY_J1", ids)

    def _write_bom(self, path: Path) -> None:
        rows = [
            {
                "Item": "",
                "Qty": "",
                "Reference": "== PASSIVE - RESISTORS ==",
                "Value": "",
                "Description": "",
                "Manufacturer": "",
                "Part Number": "",
                "Package / Footprint": "",
                "Critical Placement Distance": "",
                "Notes": "",
            },
            {
                "Item": "1",
                "Qty": "5",
                "Reference": "R1-R3 R_LED4 R_LED5",
                "Value": "220R",
                "Description": "LED resistors",
                "Manufacturer": "Yageo",
                "Part Number": "RC0805FR-07220RL",
                "Package / Footprint": "R_0805",
                "Critical Placement Distance": "",
                "Notes": "",
            },
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    def _write_j1_alias_bom(self, path: Path) -> None:
        rows = [
            {
                "Item": "1",
                "Qty": "1",
                "Reference": "J1_AC",
                "Value": "Screw Terminal 3-pin 5.0mm",
                "Description": "AC input",
                "Manufacturer": "Phoenix Contact",
                "Part Number": "1935161",
                "Package / Footprint": "5.0mm THT",
                "Critical Placement Distance": "",
                "Notes": "L/N/PE mains input.",
            }
        ]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    unittest.main()
