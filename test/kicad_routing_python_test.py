import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.kicad_automation_service import KiCadAutomationService


class KiCadRoutingTest(unittest.TestCase):
    def test_grouped_resistor_refs_are_expanded_before_virtual_endpoints(self):
        service = KiCadAutomationService()

        netlist = service._with_virtual_endpoint_components(
            {
                "components": [
                    {
                        "ref": "R10-R13",
                        "type": "resistor_array",
                        "value": "100R",
                        "manufacturer": "Yageo",
                        "part_number": "RC0603FR-07100RL",
                    }
                ],
                "nets": [
                    {"net": "SPI_CS_3V3", "pins": ["R10.1", "R10.2"]},
                    {"net": "SPI_MOSI_3V3", "pins": ["R11.1", "R11.2"]},
                    {"net": "SPI_CLK_3V3", "pins": ["R12.1", "R12.2"]},
                    {"net": "SPI_MISO_3V3", "pins": ["R13.1", "R13.2"]},
                ],
            }
        )

        refs = {component["ref"] for component in netlist["components"]}
        self.assertGreaterEqual(refs, {"R10", "R11", "R12", "R13"})
        self.assertNotIn("R10-R13", refs)
        self.assertFalse(
            any(
                component["type"] == "connector" and component["ref"] in {"R10", "R11", "R12", "R13"}
                for component in netlist["components"]
            )
        )

    def test_production_pin_aliases_resolve_to_real_pads(self):
        service = KiCadAutomationService()

        cases = [
            ("U2", "VDDIO", {"type": "uwb_module", "part_number": "DWM3000"}, "2"),
            ("U2", "RF_PIN23", {"type": "uwb_module", "part_number": "DWM3000"}, "23"),
            ("J1", "L", {"type": "ac_connector"}, "1"),
            ("J1", "N", {"type": "ac_connector"}, "2"),
            ("J2", "CENTER", {"type": "sma_connector"}, "1"),
            ("J2", "SHIELD", {"type": "sma_connector"}, "2"),
            ("U7", "SW_OUT", {"type": "buck", "part_number": "TPS54331DR"}, "5"),
            ("U7", "GND", {"type": "buck", "part_number": "TPS54331DR"}, "6"),
        ]

        for ref, pin, component, expected in cases:
            with self.subTest(ref=ref, pin=pin):
                self.assertEqual(service._resolve_pad_number(ref, pin, component), expected)

    def test_ac_connector_uses_existing_kicad_terminal_block(self):
        import pcbnew  # type: ignore[import-not-found]

        service = KiCadAutomationService()
        footprint = service._footprint_for_component(
            pcbnew,
            pcbnew.BOARD(),
            {"ref": "J1", "type": "ac_connector", "part_number": "AC input"},
        )

        self.assertEqual(footprint.GetFPID().GetLibItemName(), "TerminalBlock_Phoenix_PT-1,5-2-3.5-H_1x02_P3.50mm_Horizontal")

    def test_generated_tracks_keep_their_net_assignment(self):
        import pcbnew  # type: ignore[import-not-found]

        service = KiCadAutomationService(
            kicad_cli=r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
            project_root=str(Path(__file__).resolve().parents[1]),
        )
        board = service._create_board(
            pcbnew,
            {
                "components": [
                    {
                        "ref": f"X{index + 1}",
                        "type": "test_point",
                        "value": "TP",
                        "part_number": "",
                    }
                    for index in range(10)
                ],
                "nets": [
                    {
                        "net": "SIG_TEST",
                        "net_class": "signal",
                        "pins": ["X1.1", "X10.1"],
                    }
                ],
            },
        )

        tracks = list(board.GetTracks())
        self.assertGreater(len(tracks), 0)
        self.assertTrue(
            all(track.GetNetname() == "SIG_TEST" for track in tracks),
            [track.GetNetname() for track in tracks],
        )
        self.assertGreaterEqual(
            {track.GetLayerName() for track in tracks},
            {"F.Cu", "B.Cu"},
        )


if __name__ == "__main__":
    unittest.main()
