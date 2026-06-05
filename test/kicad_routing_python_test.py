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
            ("J2", "SHIELD", {"type": "sma_connector"}, ("2", "2", "2", "2")),
            ("U4", "SW_OUT", {"type": "buck", "part_number": "TPS54331DR"}, "8"),
            ("U4", "GND", {"type": "buck", "part_number": "TPS54331DR"}, "7"),
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
            {"ref": "J1", "type": "ac_connector", "part_number": "1803578"},
        )

        self.assertEqual(footprint.GetFPID().GetLibItemName(), "TerminalBlock_Phoenix_PT-1,5-3-5.0-H_1x03_P5.00mm_Horizontal")

    def test_fixed_board_anchor_placement_keeps_sockets_outside_hlk_body(self):
        service = KiCadAutomationService()

        sk1_x, _ = service._placement_for_component({"ref": "SK1", "type": "socket"}, 0)
        sk2_x, _ = service._placement_for_component({"ref": "SK2", "type": "socket"}, 0)
        j1_x, j1_y = service._placement_for_component({"ref": "J1", "type": "ac_connector"}, 0)
        u4_x, u4_y = service._placement_for_component(
            {"ref": "U4", "type": "buck", "part_number": "TPS54331DR"},
            0,
        )

        self.assertGreaterEqual(sk1_x, 62.0)
        self.assertGreaterEqual(sk2_x, 62.0)
        self.assertLessEqual(j1_x, 4.0)
        self.assertLessEqual(j1_y, 14.0)
        self.assertGreaterEqual(u4_x, 68.0)
        self.assertLessEqual(u4_y, 10.0)

    def test_decoupling_is_not_generated_for_dnp_source_only_ics(self):
        service = KiCadAutomationService()

        enriched = service._enrich_netlist(
            {
                "components": [
                    {"ref": "U15", "type": "ethernet_controller", "part_number": "W5500"},
                    {"ref": "U6", "type": "level_shifter", "part_number": "TXB0104RGYR"},
                ],
                "nets": [],
            }
        )

        generated_caps = [c for c in enriched["components"] if str(c.get("reason", "")).endswith("decoupling")]
        self.assertTrue(any(c["ref"].startswith("C") for c in generated_caps))
        self.assertFalse(any(c["reason"].startswith("U15 ") for c in generated_caps))
        self.assertFalse(any("anchor" in c for c in generated_caps))

    def test_uwb_spi_series_resistors_are_split_into_real_series_nets(self):
        service = KiCadAutomationService()

        enriched = service._enrich_netlist(
            {
                "components": [
                    {"ref": "SK2", "type": "socket", "part_number": "61302211821"},
                    {"ref": "U6", "type": "level_shifter", "part_number": "TXB0104RGYR"},
                    *[
                        {"ref": ref, "type": "resistor", "part_number": "RC0805FR-07100RL"}
                        for ref in ("R20", "R21", "R22", "R23")
                    ],
                ],
                "nets": [
                    {"net": "SPI_CS_3V3", "pins": ["SK2.14", "R20.1", "R20.2", "U6.A1"]},
                    {"net": "SPI_MOSI_3V3", "pins": ["SK2.13", "R21.1", "R21.2", "U6.A2"]},
                    {"net": "SPI_CLK_3V3", "pins": ["SK2.12", "R22.1", "R22.2", "U6.A3"]},
                    {"net": "SPI_MISO_3V3", "pins": ["SK2.11", "R23.1", "R23.2", "U6.A4"]},
                ],
            }
        )

        nets = {net["net"]: set(net["pins"]) for net in enriched["nets"]}
        self.assertEqual(nets["SPI_MISO_3V3_MCU"], {"SK2.11", "R23.1"})
        self.assertEqual(nets["SPI_MISO_3V3"], {"R23.2", "U6.A4"})
        self.assertEqual(nets["SPI_CS_3V3_MCU"], {"SK2.14", "R20.1"})
        self.assertEqual(nets["SPI_CS_3V3"], {"R20.2", "U6.A1"})

    def test_bypass_power_nets_are_canonicalized_to_real_rails(self):
        service = KiCadAutomationService()

        enriched = service._enrich_netlist(
            {
                "components": [],
                "nets": [
                    {"net": "+1V8_BYPASS", "pins": ["C30.1"]},
                    {"net": "+3V3_BYPASS", "pins": ["C29.1"]},
                    {"net": "+5V_BYPASS", "pins": ["C21.1"]},
                    {"net": "GND_BYPASS", "pins": ["C30.2"]},
                ],
            }
        )

        nets = {net["net"]: set(net["pins"]) for net in enriched["nets"]}
        self.assertIn("C30.1", nets["+1V8"])
        self.assertIn("C29.1", nets["+3V3_L"])
        self.assertIn("C21.1", nets["+5V_ISO"])
        self.assertIn("C30.2", nets["GND"])
        self.assertNotIn("+1V8_BYPASS", nets)
        self.assertNotIn("+3V3_BYPASS", nets)
        self.assertNotIn("+5V_BYPASS", nets)
        self.assertNotIn("GND_BYPASS", nets)

    def test_spi_source_termination_resistors_anchor_below_socket_bank(self):
        service = KiCadAutomationService()

        expected = {
            "R20": (96.0, 39.0),
            "R21": (92.0, 39.0),
            "R22": (88.0, 39.0),
            "R23": (84.0, 39.0),
        }

        for ref, position in expected.items():
            with self.subTest(ref=ref):
                self.assertEqual(
                    service._placement_for_component(
                        {"ref": ref, "type": "resistor", "part_number": "RC0805FR-07100RL"},
                        0,
                    ),
                    position,
                )

    def test_backside_placement_flips_smd_pad_layers(self):
        import pcbnew  # type: ignore[import-not-found]

        service = KiCadAutomationService()
        footprint = service._footprint_for_component(
            pcbnew,
            board := pcbnew.BOARD(),
            {"ref": "C1", "type": "capacitor", "part_number": "GRM188R71C104KA93D"},
        )
        footprint.SetPosition(pcbnew.VECTOR2I_MM(20, 20))
        board.Add(footprint)

        service._place_footprint_on_back(pcbnew, footprint)

        self.assertEqual(footprint.GetLayer(), pcbnew.B_Cu)
        for pad in footprint.Pads():
            self.assertTrue(pad.GetLayerSet().Contains(pcbnew.B_Cu))
            self.assertFalse(pad.GetLayerSet().Contains(pcbnew.F_Cu))

    def test_board_generation_delegates_copper_routing_to_freerouting(self):
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

        self.assertEqual(list(board.GetTracks()), [])


if __name__ == "__main__":
    unittest.main()
