import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.design_feasibility_service import DesignFeasibilityService


class DesignFeasibilityServiceTest(unittest.TestCase):
    def test_reviews_overcrowded_fixed_130x46_design(self):
        with tempfile.TemporaryDirectory() as tmp:
            netlist = Path(tmp) / "netlist.json"
            netlist.write_text(
                json.dumps(
                    {
                        "source_prompt": (
                            "U1 = ESP32 module 18mm x 20mm.\n"
                            "KARAR-3: BOARD BOYUTU DEGISMEZ. BOYUT: 130mm x 46mm."
                        ),
                        "components": [
                            {"ref": f"R{i}", "type": "resistor", "footprint": "R_0603"}
                            for i in range(130)
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = DesignFeasibilityService().audit(netlist)

        self.assertEqual(report.status, "review")
        self.assertEqual(report.board_size_mm, (130.0, 46.0))
        self.assertTrue(report.fixed_board_constraint)
        self.assertEqual(report.pcb_mounted_count, 130)
        self.assertEqual(report.recommended_actions, [])

    def test_passes_small_board_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            netlist = Path(tmp) / "netlist.json"
            netlist.write_text(
                json.dumps(
                    {
                        "board_size_mm": [130, 46],
                        "components": [
                            {"ref": "U1", "type": "virtual_module", "footprint": "not_pcb_mounted"},
                            {"ref": "U2", "type": "uwb_module", "footprint": "DWM3000"},
                            {"ref": "C1", "type": "capacitor", "footprint": "C_0603"},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            report = DesignFeasibilityService().audit(netlist)

        self.assertEqual(report.status, "pass")
        self.assertEqual(report.pcb_mounted_count, 2)


if __name__ == "__main__":
    unittest.main()
