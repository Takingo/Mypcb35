import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.engineering_readiness_service import EngineeringReadinessService
from engine.fabrication_api_service import run as run_fabrication_package
from engine.design_evidence_gate import audit_design_evidence_gate
from engine.netlist_source_normalizer import normalize_design_source
from engine.board_verification_manifest import build_board_verification_manifest
from engine.pcba_manufacturing_export_service import PcbaManufacturingExportService


class EngineeringGateTest(unittest.TestCase):
    def test_readiness_marks_pcba_and_zip_blocked_when_drc_is_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                bom = root / "BOM.csv"
                bom.write_text(
                    "ESP32,DWM3000,HLK-5M05,TXB0104,SN74LVC1T45",
                    encoding="utf-8",
                )
                netlist = root / "AI_NETLIST_V1.json"
                netlist.write_text(_valid_netlist_json(), encoding="utf-8")

                schematic = root / "board.kicad_sch"
                schematic.write_text("(kicad_sch (symbol \"U1\"))", encoding="utf-8")
                erc = root / "erc_report.json"
                erc.write_text(json.dumps({"sheets": []}), encoding="utf-8")

                pcb = root / "board.kicad_pcb"
                pcb.write_text("(kicad_pcb (footprint \"U1\"))", encoding="utf-8")

                layout = root / "layout_optimization_status.json"
                layout.write_text(
                    json.dumps(
                        {"final_violation_count": 12, "manufacturing_ready": False}
                    ),
                    encoding="utf-8",
                )

                simulation_dir = root / "outputs" / "simulation"
                simulation_dir.mkdir(parents=True)
                (simulation_dir / "simulation_report.json").write_text(
                    json.dumps({"results": [{"status": "pass"}]}),
                    encoding="utf-8",
                )

                fabrication = root / "fabrication_package.json"
                fabrication.write_text(
                    json.dumps(
                        {
                            "files": [
                                {"category": "gerber"},
                                {"category": "drill"},
                                {"category": "pick_and_place"},
                                {"category": "bom"},
                            ]
                        }
                    ),
                    encoding="utf-8",
                )

                production_zip = root / "package.zip"
                with zipfile.ZipFile(production_zip, "w") as archive:
                    archive.writestr("gerber/top.gbr", "gbr")
                    archive.writestr("drill/board.drl", "drl")
                    archive.writestr("position/pnp.csv", "pnp")
                    archive.writestr("bom/BOM.csv", "bom")

                report = EngineeringReadinessService().audit(
                    schematic_file=schematic,
                    erc_report_file=erc,
                    pcb_file=pcb,
                    backup_pcb_file=root / "backup.kicad_pcb",
                    bom_file=bom,
                    netlist_file=netlist,
                    layout_status_file=layout,
                    drc_report_file=root / "missing_drc.json",
                    verification_manifest_file=root / "missing_manifest.json",
                    fabrication_package_file=fabrication,
                    production_zip=production_zip,
                    output_path=root / "engineering.json",
                    asset_output=None,
                )
            finally:
                os.chdir(previous_cwd)

        checks = {check.id: check for check in report.checks}
        self.assertEqual(checks["DRC_EVIDENCE"].status, "fail")
        self.assertEqual(checks["PCBA_HANDOFF"].status, "fail")
        self.assertEqual(checks["FAB_ZIP"].status, "fail")
        self.assertEqual(report.overall_status, "blocked")

    def test_readiness_blocks_synthetic_footprint_even_with_clean_drc_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                bom = root / "BOM.csv"
                bom.write_text(
                    "ESP32,DWM3000,HLK-5M05,TXB0104,SN74LVC1T45",
                    encoding="utf-8",
                )
                netlist = root / "AI_NETLIST_V1.json"
                netlist.write_text(_valid_netlist_json(), encoding="utf-8")
                schematic = root / "board.kicad_sch"
                schematic.write_text("(kicad_sch (symbol \"U1\"))", encoding="utf-8")
                erc = root / "erc_report.json"
                erc.write_text(json.dumps({"sheets": []}), encoding="utf-8")
                pcb = root / "board.kicad_pcb"
                pcb.write_text(
                    '(kicad_pcb (footprint "" (property "Reference" "U2")))',
                    encoding="utf-8",
                )
                layout = root / "layout_optimization_status.json"
                layout.write_text(
                    json.dumps({"final_violation_count": 0, "manufacturing_ready": True}),
                    encoding="utf-8",
                )
                simulation_dir = root / "outputs" / "simulation"
                simulation_dir.mkdir(parents=True)
                (simulation_dir / "simulation_report.json").write_text(
                    json.dumps({"results": [{"status": "pass"}]}),
                    encoding="utf-8",
                )

                report = EngineeringReadinessService().audit(
                    schematic_file=schematic,
                    erc_report_file=erc,
                    pcb_file=pcb,
                    backup_pcb_file=root / "backup.kicad_pcb",
                    bom_file=bom,
                    netlist_file=netlist,
                    layout_status_file=layout,
                    drc_report_file=root / "missing_drc.json",
                    verification_manifest_file=root / "missing_manifest.json",
                    fabrication_package_file=root / "missing.json",
                    production_zip=root / "missing.zip",
                    output_path=root / "engineering.json",
                    asset_output=None,
                )
            finally:
                os.chdir(previous_cwd)

        checks = {check.id: check for check in report.checks}
        self.assertEqual(checks["DRC_EVIDENCE"].status, "pass")
        self.assertEqual(checks["PRODUCTION_MODEL"].status, "fail")
        self.assertEqual(report.overall_status, "blocked")

    def test_readiness_blocks_empty_local_ai_netlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            previous_cwd = Path.cwd()
            os.chdir(root)
            try:
                bom = root / "BOM.csv"
                bom.write_text(
                    "ESP32,DWM3000,HLK-5M05,TXB0104,SN74LVC1T45",
                    encoding="utf-8",
                )
                netlist = root / "AI_NETLIST_V1.json"
                netlist.write_text(
                    json.dumps(
                        {
                            "schema": "AI_Netlist_v1",
                            "components": [],
                            "nets": [],
                        }
                    ),
                    encoding="utf-8",
                )
                schematic = root / "board.kicad_sch"
                schematic.write_text("(kicad_sch (symbol \"U1\"))", encoding="utf-8")
                erc = root / "erc_report.json"
                erc.write_text(json.dumps({"sheets": []}), encoding="utf-8")
                pcb = root / "board.kicad_pcb"
                pcb.write_text("(kicad_pcb (footprint \"U1\"))", encoding="utf-8")
                layout = root / "layout_optimization_status.json"
                layout.write_text(
                    json.dumps({"final_violation_count": 0, "manufacturing_ready": True}),
                    encoding="utf-8",
                )
                simulation_dir = root / "outputs" / "simulation"
                simulation_dir.mkdir(parents=True)
                (simulation_dir / "simulation_report.json").write_text(
                    json.dumps({"results": [{"status": "pass"}]}),
                    encoding="utf-8",
                )

                report = EngineeringReadinessService().audit(
                    schematic_file=schematic,
                    erc_report_file=erc,
                    pcb_file=pcb,
                    backup_pcb_file=root / "backup.kicad_pcb",
                    bom_file=bom,
                    netlist_file=netlist,
                    layout_status_file=layout,
                    drc_report_file=root / "missing_drc.json",
                    verification_manifest_file=root / "missing_manifest.json",
                    fabrication_package_file=root / "missing.json",
                    production_zip=root / "missing.zip",
                    output_path=root / "engineering.json",
                    asset_output=None,
                )
            finally:
                os.chdir(previous_cwd)

        checks = {check.id: check for check in report.checks}
        self.assertEqual(checks["DESIGN_SOURCE_EVIDENCE"].status, "fail")
        self.assertIn("no components", checks["DESIGN_SOURCE_EVIDENCE"].evidence)
        self.assertEqual(report.overall_status, "blocked")

    def test_fabrication_package_refuses_to_package_when_drc_is_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase4 = root / "phase4"
            (phase4 / "gerber").mkdir(parents=True)
            (phase4 / "drill").mkdir()
            (phase4 / "position").mkdir()
            (phase4 / "gerber" / "top.gbr").write_text("gbr", encoding="utf-8")
            (phase4 / "drill" / "board.drl").write_text("drl", encoding="utf-8")
            (phase4 / "position" / "pnp.csv").write_text("pnp", encoding="utf-8")

            bom = root / "BOM.csv"
            bom.write_text("ESP32", encoding="utf-8")
            pcb = root / "board.kicad_pcb"
            pcb.write_text(
                '(kicad_pcb (gr_line (start 0 0) (end 10 0) (layer "Edge.Cuts")))',
                encoding="utf-8",
            )
            layout = root / "layout_optimization_status.json"
            layout.write_text(
                json.dumps({"final_violation_count": 3, "manufacturing_ready": False}),
                encoding="utf-8",
            )

            with self.assertRaises(RuntimeError):
                run_fabrication_package(
                    phase4_dir=phase4,
                    pcb_file=pcb,
                    bom_file=bom,
                    output_dir=root / "fabrication",
                    manufacturer="PCBWay",
                    quantity=5,
                    layers=4,
                    solder_mask_color="Green",
                    asset_output=None,
                    layout_status_file=layout,
                )

    def test_fabrication_package_refuses_synthetic_footprint_even_when_drc_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            phase4 = root / "phase4"
            (phase4 / "gerber").mkdir(parents=True)
            (phase4 / "drill").mkdir()
            (phase4 / "position").mkdir()
            (phase4 / "gerber" / "top.gbr").write_text("gbr", encoding="utf-8")
            (phase4 / "drill" / "board.drl").write_text("drl", encoding="utf-8")
            (phase4 / "position" / "pnp.csv").write_text("pnp", encoding="utf-8")

            bom = root / "BOM.csv"
            bom.write_text("ESP32", encoding="utf-8")
            pcb = root / "board.kicad_pcb"
            pcb.write_text(
                '(kicad_pcb (footprint "" (property "Reference" "U2")))',
                encoding="utf-8",
            )
            layout = root / "layout_optimization_status.json"
            layout.write_text(
                json.dumps({"final_violation_count": 0, "manufacturing_ready": True}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(RuntimeError, "production model validation failed"):
                run_fabrication_package(
                    phase4_dir=phase4,
                    pcb_file=pcb,
                    bom_file=bom,
                    output_dir=root / "fabrication",
                    manufacturer="PCBWay",
                    quantity=5,
                    layers=4,
                    solder_mask_color="Green",
                    asset_output=None,
                    layout_status_file=layout,
                )

    def test_pcba_direct_export_refuses_empty_ai_netlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bom = root / "BOM.csv"
            bom.write_text(
                "ESP32-S3-WROOM-1,DWM3000,HLK-5M05,TXB0104",
                encoding="utf-8",
            )
            netlist = root / "AI_NETLIST_V1.json"
            netlist.write_text(
                json.dumps({"schema": "AI_Netlist_v1", "components": [], "nets": []}),
                encoding="utf-8",
            )
            layout = root / "layout_optimization_status.json"
            layout.write_text(
                json.dumps({"final_violation_count": 0, "manufacturing_ready": True}),
                encoding="utf-8",
            )
            pcb = root / "board.kicad_pcb"
            pcb.write_text('(kicad_pcb (footprint "U1"))', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "design source evidence failed"):
                PcbaManufacturingExportService().validate_export_gate(
                    netlist_file=netlist,
                    bom_file=bom,
                    layout_status_file=layout,
                    pcb_file=pcb,
                )

    def test_pcba_direct_export_refuses_dirty_drc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bom = root / "BOM.csv"
            bom.write_text(
                "ESP32-S3-WROOM-1,DWM3000,HLK-5M05,TXB0104",
                encoding="utf-8",
            )
            netlist = root / "AI_NETLIST_V1.json"
            netlist.write_text(_valid_netlist_json(), encoding="utf-8")
            layout = root / "layout_optimization_status.json"
            layout.write_text(
                json.dumps({"final_violation_count": 7, "manufacturing_ready": False}),
                encoding="utf-8",
            )
            pcb = root / "board.kicad_pcb"
            pcb.write_text('(kicad_pcb (footprint "U1"))', encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "KiCad DRC is not clean"):
                PcbaManufacturingExportService().validate_export_gate(
                    netlist_file=netlist,
                    bom_file=bom,
                    layout_status_file=layout,
                    pcb_file=pcb,
                )

    def test_source_normalizer_resolves_bom_backed_group_refs_and_aliases(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bom = root / "BOM.csv"
            bom.write_text(
                "\n".join(
                    [
                        "Reference,Quantity,Value,Manufacturer,Part Number",
                        "U1,1,MCU,Espressif,ESP32-S3-WROOM-1",
                        "U2,1,UWB,Qorvo,DWM3000",
                        "U3,1,Level shifter,Texas Instruments,TXB0104",
                        "U6,1,AC/DC,Hi-Link,HLK-5M05",
                        "K1-K2,2,Relay,Omron,G5Q-14-DC5",
                        "R10-R13,4,100R,Yageo,RC0603FR-07100RL",
                        "OK1,1,Optocoupler,Sharp,PC817X2CSP9F",
                        "Q1,1,MOSFET,Onsemi,2N7002",
                        "D1,1,Diode,Vishay,SS34-E3/57T",
                    ]
                ),
                encoding="utf-8",
            )
            source = json.loads(_valid_netlist_json())
            source["components"].extend(
                [
                    {
                        "ref": "K1",
                        "type": "relay",
                        "manufacturer": "Omron",
                        "part_number": "G5Q-14-DC5",
                    },
                    {
                        "ref": "OK1",
                        "type": "optocoupler",
                        "manufacturer": "Sharp",
                        "part_number": "PC817",
                    },
                    {
                        "ref": "Q1",
                        "type": "n_mosfet",
                        "manufacturer": "Onsemi",
                        "part_number": "2N7002",
                    },
                    {
                        "ref": "D1",
                        "type": "flyback_diode",
                        "manufacturer": "Vishay",
                        "part_number": "SS14",
                    },
                ]
            )
            source["nets"].extend(
                [
                    {"net": "+5V_ISO", "pins": ["K1.COIL+", "K2.COIL+"]},
                    {"net": "SPI_CS_3V3", "pins": ["U1.GPIO10", "R10", "U3.A1"]},
                ]
            )

            normalized = normalize_design_source(source, bom)
            refs = {component["ref"] for component in normalized["components"]}
            self.assertIn("K2", refs)
            self.assertIn("R10", refs)
            ok1 = next(component for component in normalized["components"] if component["ref"] == "OK1")
            d1 = next(component for component in normalized["components"] if component["ref"] == "D1")
            self.assertEqual(ok1["part_number"], "PC817X2CSP9F")
            self.assertEqual(d1["part_number"], "SS34-E3/57T")

            netlist = root / "AI_NETLIST_V1.json"
            netlist.write_text(json.dumps(source), encoding="utf-8")
            gate = audit_design_evidence_gate(netlist, bom)
            self.assertTrue(gate.ok, gate.evidence_summary)

    def test_board_verification_manifest_counts_drc_and_unconnected_as_blockers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bom = root / "BOM.csv"
            bom.write_text(
                "ESP32,DWM3000,HLK-5M05,TXB0104,SN74LVC1T45",
                encoding="utf-8",
            )
            netlist = root / "AI_NETLIST_V1.json"
            netlist.write_text(_valid_netlist_json(), encoding="utf-8")
            pcb = root / "board.kicad_pcb"
            pcb.write_text('(kicad_pcb (footprint "U1"))', encoding="utf-8")
            drc = root / "drc_report.json"
            drc.write_text(
                json.dumps(
                    {
                        "kicad_version": "10.0.3",
                        "violations": [{"type": "silk_overlap", "severity": "warning"}],
                        "unconnected_items": [{"description": "Missing connection"}],
                    }
                ),
                encoding="utf-8",
            )

            manifest = build_board_verification_manifest(
                pcb_file=pcb,
                drc_report_file=drc,
                netlist_file=netlist,
                bom_file=bom,
            )

        self.assertFalse(manifest.manufacturing_ready)
        self.assertEqual(manifest.total_findings, 2)
        self.assertEqual(manifest.unconnected_count, 1)
        self.assertEqual(manifest.error_count, 1)


def _valid_netlist_json() -> str:
    return json.dumps(
        {
            "schema": "AI_Netlist_v1",
            "components": [
                {
                    "ref": "U1",
                    "type": "mcu",
                    "manufacturer": "Espressif",
                    "part_number": "ESP32-S3-WROOM-1",
                },
                {
                    "ref": "U2",
                    "type": "uwb_module",
                    "manufacturer": "Qorvo",
                    "part_number": "DWM3000",
                },
                {
                    "ref": "U6",
                    "type": "ac_dc",
                    "manufacturer": "Hi-Link",
                    "part_number": "HLK-5M05",
                },
                {
                    "ref": "U3",
                    "type": "level_shifter",
                    "manufacturer": "Texas Instruments",
                    "part_number": "TXB0104",
                },
            ],
            "nets": [
                {"net": "GND", "pins": ["U1.GND", "U2.GND"]},
                {"net": "+3V3", "pins": ["U1.3V3", "U3.VCCA"]},
            ],
        }
    )


if __name__ == "__main__":
    unittest.main()
