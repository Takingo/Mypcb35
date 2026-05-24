from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


MM = 1_000_000
DWM3000_REQUIRED_PITCH_MM = 1.0


class KiCadAutomationError(RuntimeError):
    """Raised when the KiCad bridge cannot complete a requested operation."""


@dataclass(frozen=True)
class KiCadProjectArtifacts:
    project_name: str
    project_dir: str
    pro_file: str
    schematic_file: str
    pcb_file: str
    manufacturing_dir: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CliResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class ManufacturingRun:
    artifacts: KiCadProjectArtifacts
    drc: CliResult
    gerber: CliResult | None
    drill: CliResult | None
    position: CliResult | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KiCadAutomationService:
    """Bridge between AI_Netlist_v1 and KiCad's headless tooling.

    The service is intentionally split into two layers:
    - `pcbnew` creates or mutates KiCad board geometry and injects constraints.
    - `kicad-cli` runs DRC and manufacturing exports in subprocesses.

    The code imports `pcbnew` lazily because normal Python environments often
    do not expose KiCad's embedded Python package on PATH. In production, run
    this module with KiCad's Python environment or configure PYTHONPATH to the
    KiCad scripting package.
    """

    def __init__(self, kicad_cli: str = "kicad-cli") -> None:
        self.kicad_cli = kicad_cli

    def create_project_from_ai_netlist(
        self,
        netlist_json: Path,
        output_root: Path,
    ) -> KiCadProjectArtifacts:
        netlist = self._with_virtual_endpoint_components(self._read_ai_netlist(netlist_json))
        project_name = self._safe_project_name(netlist.get("project_name", "omnicircuit_project"))
        project_dir = output_root / project_name
        project_dir.mkdir(parents=True, exist_ok=True)

        pro_file = project_dir / f"{project_name}.kicad_pro"
        schematic_file = project_dir / f"{project_name}.kicad_sch"
        pcb_file = project_dir / f"{project_name}.kicad_pcb"
        manufacturing_dir = project_dir / "manufacturing"
        manufacturing_dir.mkdir(exist_ok=True)

        warnings: list[str] = []
        self._write_project_file(pro_file, project_name)
        self._write_schematic_draft(schematic_file, netlist)

        try:
            pcbnew = self._import_pcbnew()
            board = self._create_board(pcbnew, netlist)
            self._inject_design_rules(pcbnew, board, netlist)
            pcbnew.SaveBoard(str(pcb_file), board)
        except Exception as exc:  # noqa: BLE001 - keep backend usable without KiCad Python.
            warnings.append(f"pcbnew automation unavailable: {exc}")
            self._write_pcbnew_unavailable_stub(pcb_file, netlist, str(exc))

        return KiCadProjectArtifacts(
            project_name=project_name,
            project_dir=str(project_dir),
            pro_file=str(pro_file),
            schematic_file=str(schematic_file),
            pcb_file=str(pcb_file),
            manufacturing_dir=str(manufacturing_dir),
            warnings=warnings,
        )

    async def run_manufacturing_pipeline(
        self,
        artifacts: KiCadProjectArtifacts,
        *,
        continue_on_drc_error: bool = False,
    ) -> ManufacturingRun:
        pcb_file = Path(artifacts.pcb_file)
        manufacturing_dir = Path(artifacts.manufacturing_dir)
        gerber_dir = manufacturing_dir / "gerber"
        drill_dir = manufacturing_dir / "drill"
        position_dir = manufacturing_dir / "position"
        gerber_dir.mkdir(parents=True, exist_ok=True)
        drill_dir.mkdir(parents=True, exist_ok=True)
        position_dir.mkdir(parents=True, exist_ok=True)

        self._require_kicad_cli()
        drc_report = manufacturing_dir / "drc_report.json"
        drc = await self.run_drc(pcb_file, drc_report)
        drc_summary = self.parse_drc_report(drc_report)
        has_drc_violations = len(drc_summary.get("violations", [])) > 0
        if (not drc.ok or has_drc_violations) and not continue_on_drc_error:
            return ManufacturingRun(artifacts, drc, None, None, None)

        gerber = await self.export_gerber(pcb_file, gerber_dir)
        drill = await self.export_drill(pcb_file, drill_dir)
        position = await self.export_position(pcb_file, position_dir)
        return ManufacturingRun(artifacts, drc, gerber, drill, position)

    async def run_drc(self, pcb_file: Path, report_file: Path) -> CliResult:
        return await self._run_cli(
            [
                self.kicad_cli,
                "pcb",
                "drc",
                "--format",
                "json",
                "--output",
                str(report_file),
                str(pcb_file),
            ]
        )

    async def export_gerber(self, pcb_file: Path, output_dir: Path) -> CliResult:
        return await self._run_cli(
            [
                self.kicad_cli,
                "pcb",
                "export",
                "gerbers",
                "--output",
                str(output_dir),
                str(pcb_file),
            ]
        )

    async def export_drill(self, pcb_file: Path, output_dir: Path) -> CliResult:
        return await self._run_cli(
            [
                self.kicad_cli,
                "pcb",
                "export",
                "drill",
                "--output",
                str(output_dir),
                str(pcb_file),
            ]
        )

    async def export_position(self, pcb_file: Path, output_dir: Path) -> CliResult:
        output_file = output_dir / "pick_and_place.csv"
        return await self._run_cli(
            [
                self.kicad_cli,
                "pcb",
                "export",
                "pos",
                "--output",
                str(output_file),
                "--format",
                "csv",
                "--units",
                "mm",
                str(pcb_file),
            ]
        )

    def parse_drc_report(self, report_file: Path) -> dict[str, Any]:
        if not report_file.exists():
            return {
                "status": "missing",
                "violations": [],
                "summary": "DRC report file was not produced.",
            }
        try:
            report = json.loads(report_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "status": "unparsed",
                "violations": [],
                "summary": "DRC report exists but is not valid JSON.",
            }

        violations = report.get("violations") or report.get("items") or []
        return {
            "status": "pass" if len(violations) == 0 else "fail",
            "violations": violations,
            "summary": f"{len(violations)} DRC violation(s) reported.",
        }

    def _read_ai_netlist(self, netlist_json: Path) -> dict[str, Any]:
        data = json.loads(netlist_json.read_text(encoding="utf-8"))
        schema = data.get("schema")
        if schema != "AI_Netlist_v1":
            raise KiCadAutomationError(f"Unsupported netlist schema: {schema}")
        return data

    def _with_virtual_endpoint_components(self, netlist: dict[str, Any]) -> dict[str, Any]:
        """Add explicit connector symbols for net endpoints omitted from the BOM.

        A real schematic cannot silently drop references such as J1 or J2 just
        because they were inferred by the cognitive netlist. This keeps RF and
        AC endpoints visible in KiCad ERC/DRC instead of hiding one-sided nets.
        """
        components = list(netlist.get("components", []))
        known_refs = {str(component.get("ref", "")) for component in components}
        endpoint_refs: set[str] = set()
        for net in netlist.get("nets", []):
            for pin_str in net.get("pins", []):
                ref, _, _pin = str(pin_str).partition(".")
                if ref and ref not in known_refs:
                    endpoint_refs.add(ref)

        for ref in sorted(endpoint_refs):
            value = "SMA antenna connector" if ref.upper() == "J2" else "External connector"
            components.append(
                {
                    "ref": ref,
                    "type": "connector",
                    "value": value,
                    "manufacturer": "Generic",
                    "part_number": value,
                    "footprint": "Connector",
                    "reason": "Virtual endpoint inferred from AI netlist pins.",
                    "constraints": [],
                }
            )

        enriched = dict(netlist)
        enriched["components"] = components
        return enriched

    def _import_pcbnew(self) -> Any:
        try:
            import pcbnew  # type: ignore[import-not-found]
        except ImportError as exc:
            raise KiCadAutomationError(
                "KiCad pcbnew Python module is not available. "
                "Run this service inside KiCad's Python environment or expose KiCad scripting libraries."
            ) from exc
        return pcbnew

    def _create_board(self, pcbnew: Any, netlist: dict[str, Any]) -> Any:
        board = pcbnew.BOARD()
        self._add_board_outline(pcbnew, board)
        net_map = self._create_nets(pcbnew, board, netlist)

        x_mm = 20.0
        y_mm = 20.0
        for index, component in enumerate(netlist.get("components", [])):
            footprint = self._footprint_for_component(pcbnew, board, component)
            footprint.SetReference(component.get("ref", f"U{index + 1}"))
            footprint.SetValue(component.get("value", component.get("part_number", "")))
            place_x, place_y = self._placement_for_component(component, index, x_mm, y_mm)
            footprint.SetPosition(self._vector(pcbnew, place_x, place_y))
            self._attach_component_nets(footprint, component, netlist, net_map)
            board.Add(footprint)

        return board

    def _add_board_outline(self, pcbnew: Any, board: Any) -> None:
        # The outline is a conservative placeholder. The final board dimensions
        # should come from mechanical constraints before fabrication export.
        points = [(0, 0), (120, 0), (120, 80), (0, 80), (0, 0)]
        for start, end in zip(points, points[1:]):
            segment = pcbnew.PCB_SHAPE(board)
            segment.SetShape(pcbnew.SHAPE_T_SEGMENT)
            segment.SetStart(self._vector(pcbnew, start[0], start[1]))
            segment.SetEnd(self._vector(pcbnew, end[0], end[1]))
            segment.SetLayer(pcbnew.Edge_Cuts)
            segment.SetWidth(self._from_mm(pcbnew, 0.1))
            board.Add(segment)

    def _create_nets(self, pcbnew: Any, board: Any, netlist: dict[str, Any]) -> dict[str, Any]:
        net_map: dict[str, Any] = {}
        for net in netlist.get("nets", []):
            name = net.get("net")
            if not name:
                continue
            net_info = pcbnew.NETINFO_ITEM(board, name)
            board.Add(net_info)
            net_map[name] = net_info
        return net_map

    def _footprint_for_component(self, pcbnew: Any, board: Any, component: dict[str, Any]) -> Any:
        ref = component.get("ref", "")
        part_number = component.get("part_number", "")
        component_type = component.get("type", "")
        footprint = pcbnew.FOOTPRINT(board)

        if ref == "J1":
            self._populate_two_pin_vertical_footprint(pcbnew, footprint, pitch_mm=10.0, pad_width_mm=1.6, pad_height_mm=1.6)
        elif ref == "J2":
            self._populate_connector_footprint(pcbnew, footprint, pad_count=2, pitch_mm=5.08)
        elif part_number == "DWM3000" or component_type == "uwb_module":
            self._populate_dwm3000_footprint(pcbnew, footprint)
        elif component_type == "ac_dc":
            self._populate_hlk_acdc_footprint(pcbnew, footprint)
        elif component_type == "varistor":
            self._populate_two_pin_vertical_footprint(pcbnew, footprint, pitch_mm=10.0, pad_width_mm=1.2, pad_height_mm=1.6)
        elif component_type == "fuse":
            self._populate_two_pin_vertical_footprint(pcbnew, footprint, pitch_mm=10.0, pad_width_mm=1.2, pad_height_mm=1.6)
        elif component_type in {"level_shifter", "mcu", "relay"}:
            self._populate_generic_ic_footprint(pcbnew, footprint, pad_count=8)
        elif ref.startswith("J"):
            self._populate_connector_footprint(pcbnew, footprint, pad_count=4)
        else:
            self._populate_passive_footprint(pcbnew, footprint)

        return footprint

    def _placement_for_component(
        self,
        component: dict[str, Any],
        index: int,
        default_x_mm: float,
        default_y_mm: float,
    ) -> tuple[float, float]:
        ref = component.get("ref", "")
        component_type = component.get("type", "")
        if ref == "U1":
            return 64.0, 20.0
        if ref == "J1":
            return 10.0, 30.0
        if ref == "J2":
            return 104.0, 24.0
        if ref == "F1":
            return 20.0, 25.0
        if ref == "MOV1":
            return 28.0, 30.0
        if ref == "U6":
            return 40.0, 30.0
        if component_type in {"uwb_module", "level_shifter"}:
            return 76.0 + (index % 3) * 12.0, 24.0 + (index // 3) * 12.0
        if component_type in {"ac_dc", "fuse", "varistor"}:
            return 18.0 + (index % 3) * 10.0, 18.0 + (index // 3) * 12.0
        if component_type in {"relay", "optocoupler", "n_mosfet"}:
            return 66.0 + (index % 4) * 12.0, 56.0 + (index // 4) * 10.0
        if ref.startswith("J"):
            return 104.0, 18.0 + (index % 4) * 12.0
        return default_x_mm + (index % 5) * 18.0, default_y_mm + (index // 5) * 16.0

    def _populate_dwm3000_footprint(self, pcbnew: Any, footprint: Any) -> None:
        # Hardware-critical constraint: DWM3000 castellated/module pads use
        # 1.0mm pitch here. Do not relax this to 1.27mm headers.
        for pad_number in range(1, 25):
            pad = self._smd_pad(pcbnew, footprint, str(pad_number), 0.65, 1.4)
            side = -1 if pad_number <= 12 else 1
            row_index = pad_number - 1 if pad_number <= 12 else pad_number - 13
            pad.SetPosition(self._vector(pcbnew, side * 7.0, (row_index - 5.5) * DWM3000_REQUIRED_PITCH_MM))
            footprint.Add(pad)

    def _populate_generic_ic_footprint(self, pcbnew: Any, footprint: Any, pad_count: int) -> None:
        half = pad_count // 2
        for pad_number in range(1, pad_count + 1):
            pad = self._smd_pad(pcbnew, footprint, str(pad_number), 0.55, 1.2)
            side = -1 if pad_number <= half else 1
            row_index = pad_number - 1 if pad_number <= half else pad_number - half - 1
            pad.SetPosition(self._vector(pcbnew, side * 2.2, (row_index - (half - 1) / 2) * 0.65))
            footprint.Add(pad)

    def _populate_hlk_acdc_footprint(self, pcbnew: Any, footprint: Any) -> None:
        # Placeholder for HLK-5M05 style isolated AC/DC modules. The spacing
        # deliberately keeps primary and secondary pads separated enough for
        # the downstream AC clearance gate to reason about them.
        pad_positions = {
            "1": (-8.0, -5.0),  # AC_L
            "2": (-8.0, 5.0),   # AC_N
            "3": (8.0, -5.0),   # +VO
            "4": (8.0, 5.0),    # -VO
        }
        for pad_number, (x_mm, y_mm) in pad_positions.items():
            pad = self._smd_pad(pcbnew, footprint, pad_number, 1.2, 1.8)
            pad.SetPosition(self._vector(pcbnew, x_mm, y_mm))
            footprint.Add(pad)

    def _populate_two_pin_footprint(
        self,
        pcbnew: Any,
        footprint: Any,
        *,
        pitch_mm: float,
        pad_width_mm: float,
        pad_height_mm: float,
    ) -> None:
        for pad_number, x_mm in [("1", -pitch_mm / 2.0), ("2", pitch_mm / 2.0)]:
            pad = self._smd_pad(pcbnew, footprint, pad_number, pad_width_mm, pad_height_mm)
            pad.SetPosition(self._vector(pcbnew, x_mm, 0))
            footprint.Add(pad)

    def _populate_two_pin_vertical_footprint(
        self,
        pcbnew: Any,
        footprint: Any,
        *,
        pitch_mm: float,
        pad_width_mm: float,
        pad_height_mm: float,
    ) -> None:
        for pad_number, y_mm in [("1", -pitch_mm / 2.0), ("2", pitch_mm / 2.0)]:
            pad = self._smd_pad(pcbnew, footprint, pad_number, pad_width_mm, pad_height_mm)
            pad.SetPosition(self._vector(pcbnew, 0, y_mm))
            footprint.Add(pad)

    def _populate_connector_footprint(self, pcbnew: Any, footprint: Any, pad_count: int, pitch_mm: float = 2.54) -> None:
        for pad_number in range(1, pad_count + 1):
            pad = self._smd_pad(pcbnew, footprint, str(pad_number), 1.4, 1.4)
            pad.SetPosition(self._vector(pcbnew, (pad_number - 1) * pitch_mm, 0))
            footprint.Add(pad)

    def _populate_passive_footprint(self, pcbnew: Any, footprint: Any) -> None:
        for pad_number, x_mm in [("1", -0.8), ("2", 0.8)]:
            pad = self._smd_pad(pcbnew, footprint, pad_number, 0.9, 0.8)
            pad.SetPosition(self._vector(pcbnew, x_mm, 0))
            footprint.Add(pad)

    def _smd_pad(self, pcbnew: Any, footprint: Any, pad_number: str, width_mm: float, height_mm: float) -> Any:
        pad = pcbnew.PAD(footprint)
        pad.SetName(pad_number)
        pad.SetNumber(pad_number)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetSize(self._vector(pcbnew, width_mm, height_mm))
        layer_set = pcbnew.LSET()
        layer_set.AddLayer(pcbnew.F_Cu)
        layer_set.AddLayer(pcbnew.F_Paste)
        layer_set.AddLayer(pcbnew.F_Mask)
        pad.SetLayerSet(layer_set)
        return pad

    def _attach_component_nets(
        self,
        footprint: Any,
        component: dict[str, Any],
        netlist: dict[str, Any],
        net_map: dict[str, Any],
    ) -> None:
        ref = component.get("ref", "")
        if not ref:
            return
        for net in netlist.get("nets", []):
            net_info = net_map.get(net.get("net", ""))
            if net_info is None:
                continue
            for pin in net.get("pins", []):
                pin_ref, _, pin_name = pin.partition(".")
                if pin_ref == ref:
                    pad = footprint.FindPadByNumber(self._normalize_pad_number(ref, pin_name))
                    if pad:
                        pad.SetNet(net_info)

    def _normalize_pad_number(self, ref: str, pin_name: str) -> str:
        if ref == "U2" and pin_name == "RF_PIN23":
            return "23"
        if ref == "U6" and pin_name == "AC_L":
            return "1"
        if ref == "U6" and pin_name == "AC_N":
            return "2"
        if ref == "U6" and pin_name == "+VO":
            return "3"
        if ref == "U6" and pin_name == "-VO":
            return "4"
        if ref == "J1" and pin_name in {"L", "LINE"}:
            return "1"
        if ref == "J1" and pin_name in {"N", "NEUTRAL"}:
            return "2"
        if ref == "J2" and pin_name in {"CENTER", "RF"}:
            return "1"
        if ref == "J2" and pin_name in {"SHIELD", "GND"}:
            return "2"
        if pin_name.startswith("GPIO"):
            return pin_name.removeprefix("GPIO")
        return pin_name

    def _inject_design_rules(self, pcbnew: Any, board: Any, netlist: dict[str, Any]) -> None:
        self._inject_net_classes(pcbnew, board, netlist)
        self._inject_rf_rule_metadata(board)
        self._inject_ac_keepout_zone(pcbnew, board)

    def _inject_net_classes(self, pcbnew: Any, board: Any, netlist: dict[str, Any]) -> None:
        settings = board.GetDesignSettings()
        if hasattr(settings, "m_NetClasses"):
            rf_class = pcbnew.NETCLASSPTR("RF_50R")
            rf_class.SetClearance(self._from_mm(pcbnew, 0.3))
            rf_class.SetTrackWidth(self._from_mm(pcbnew, 0.35))
            settings.m_NetClasses.Add(rf_class)

            mains_class = pcbnew.NETCLASSPTR("MAINS_8MM")
            mains_class.SetClearance(self._from_mm(pcbnew, 8.0))
            mains_class.SetTrackWidth(self._from_mm(pcbnew, 1.0))
            settings.m_NetClasses.Add(mains_class)

        for net in netlist.get("nets", []):
            net_name = net.get("net", "")
            net_class = net.get("net_class", "")
            net_info = board.FindNet(net_name)
            if net_info is None:
                continue
            if net_class == "rf_50r" and hasattr(net_info, "SetNetClassName"):
                net_info.SetNetClassName("RF_50R")
            if net_class == "mains" and hasattr(net_info, "SetNetClassName"):
                net_info.SetNetClassName("MAINS_8MM")

    def _inject_rf_rule_metadata(self, board: Any) -> None:
        comments = [
            "RF rule: UWB_RF_50R is DWM3000 pin 23 to SMA, 50 Ohm, 0.35mm width.",
            "RF rule: no vias, test points, or components on antenna trace; 3mm keepout required.",
        ]
        title_block = board.GetTitleBlock() if hasattr(board, "GetTitleBlock") else None
        if title_block is None or not hasattr(title_block, "SetComment"):
            return
        for index, comment in enumerate(comments):
            title_block.SetComment(index, comment)

    def _inject_ac_keepout_zone(self, pcbnew: Any, board: Any) -> None:
        safety_area = pcbnew.ZONE(board)
        safety_area.SetLayer(pcbnew.F_Cu)
        safety_area.SetIsRuleArea(True)
        if hasattr(safety_area, "SetDoNotAllowTracks"):
            # This is an AC primary-side safety area, not a copper-free void.
            # Required mains-primary nets must be allowed inside it; the actual
            # isolation rule is enforced by clearance/creepage review and by
            # keeping secondary-side objects out of this corridor.
            safety_area.SetDoNotAllowTracks(False)
            safety_area.SetDoNotAllowVias(True)
            safety_area.SetDoNotAllowPads(False)

        outline = safety_area.Outline()
        outline.NewOutline()
        for x_mm, y_mm in [(5, 5), (42, 5), (42, 34), (5, 34)]:
            outline.Append(self._vector(pcbnew, x_mm, y_mm))
        board.Add(safety_area)

    def _write_project_file(self, pro_file: Path, project_name: str) -> None:
        pro_file.write_text(
            json.dumps(
                {
                    "meta": {"version": 1},
                    "project": {"name": project_name},
                    "schematic": {},
                    "board": {},
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def _write_schematic_draft(self, schematic_file: Path, netlist: dict[str, Any]) -> None:
        components = netlist.get("components", [])
        nets = netlist.get("nets", [])

        comp_pins: dict[str, list[tuple[str, str]]] = {c.get("ref", ""): [] for c in components}
        for net in nets:
            net_name = net.get("net", "")
            for pin_str in net.get("pins", []):
                ref, _, pin = pin_str.partition(".")
                if ref in comp_pins:
                    comp_pins[ref].append((pin, net_name))

        sheet_uuid = uuid.uuid4()
        body = [
            "(kicad_sch",
            "  (version 20250610)",
            "  (generator \"OmniCircuit AI\")",
            "  (generator_version \"0.1\")",
            f"  (uuid \"{uuid.uuid4()}\")",
            "  (paper \"A2\")",
            "  (title_block",
            f"    (title \"{self._escape_s_expr(netlist.get('project_name', 'OmniCircuit AI'))}\")",
            "    (comment 1 \"Auto-generated schematic with KiCad symbol instances from AI_Netlist_v1\")",
            "    (comment 2 \"Global labels preserve generated net names; ERC still requires model/library review\")",
            "  )",
        ]

        body.append("  (lib_symbols")
        for component in components:
            ref = component.get("ref", "")
            if not ref:
                continue
            schematic_ref = self._schematic_reference(ref)
            symbol_id = self._schematic_symbol_id(ref)
            pins = comp_pins.get(ref, [])
            pin_pitch = 2.54
            box_height = max(10.16, len(pins) * pin_pitch + 5.08)
            top_pin_y = ((len(pins) - 1) / 2.0) * pin_pitch
            body.extend(
                [
                    f"    (symbol \"OmniCircuit:{symbol_id}\" (in_bom yes) (on_board yes)",
                    "      (exclude_from_sim no)",
                    "      (duplicate_pin_numbers_are_jumpers no)",
                    f"      (property \"Reference\" \"{self._escape_s_expr(schematic_ref)}\" (at 0 {box_height / 2 + 2.54:.2f} 0) (effects (font (size 1.27 1.27))))",
                    f"      (property \"Value\" \"{self._escape_s_expr(component.get('value', component.get('part_number', '')))}\" (at 0 {box_height / 2 + 5.08:.2f} 0) (effects (font (size 1.27 1.27))))",
                    "      (property \"Footprint\" \"\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    "      (property \"Datasheet\" \"\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    f"      (property \"Description\" \"{self._escape_s_expr(component.get('reason', 'Generated symbol'))}\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    f"      (symbol \"{symbol_id}_0_1\"",
                    f"        (rectangle (start -7.62 {box_height / 2:.2f}) (end 7.62 {-box_height / 2:.2f}) (stroke (width 0.254) (type default)) (fill (type background)))",
                    "      )",
                    f"      (symbol \"{symbol_id}_1_1\"",
                ]
            )
            for index, (pin_name, _) in enumerate(pins):
                y_pos = top_pin_y - index * pin_pitch
                pin_number = str(index + 1)
                body.extend(
                    [
                        f"        (pin passive line (at -10.16 {y_pos:.2f} 0) (length 2.54)",
                        f"          (name \"{self._escape_s_expr(pin_name or pin_number)}\" (effects (font (size 1.0 1.0))))",
                        f"          (number \"{self._escape_s_expr(pin_number)}\" (effects (font (size 1.0 1.0))))",
                        "        )",
                    ]
                )
            body.extend(["      )", "    )"])
        body.append("  )")

        x_start = 50.80
        y_start = 50.80

        for idx, component in enumerate(components):
            ref = component.get("ref", "")
            if not ref:
                continue

            pins = comp_pins[ref]
            schematic_ref = self._schematic_reference(ref)
            symbol_id = self._schematic_symbol_id(ref)
            symbol_uuid = uuid.uuid4()
            x = x_start + (idx % 4) * 76.20
            y = y_start + (idx // 4) * 68.58
            pin_pitch = 2.54
            box_height = max(10.16, len(pins) * pin_pitch + 5.08)
            top_pin_y = ((len(pins) - 1) / 2.0) * pin_pitch

            body.extend(
                [
                    f"  (symbol (lib_id \"OmniCircuit:{symbol_id}\") (at {x:.2f} {y:.2f} 0) (unit 1)",
                    "    (in_bom yes) (on_board yes)",
                    "    (exclude_from_sim no)",
                    "    (dnp no)",
                    f"    (uuid \"{symbol_uuid}\")",
                    f"    (property \"Reference\" \"{self._escape_s_expr(schematic_ref)}\" (at {x:.2f} {y - box_height / 2 - 5.08:.2f} 0))",
                    f"    (property \"Value\" \"{self._escape_s_expr(component.get('value', component.get('part_number', '')))}\" (at {x:.2f} {y - box_height / 2 - 7.62:.2f} 0))",
                    f"    (property \"Footprint\" \"\" (at {x:.2f} {y + box_height / 2 + 4:.2f} 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    "    (property \"Datasheet\" \"\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    f"    (property \"Description\" \"{self._escape_s_expr(component.get('reason', 'Generated symbol'))}\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                ]
            )
            for pin_index in range(len(pins)):
                body.extend(
                    [
                        f"    (pin \"{pin_index + 1}\"",
                        f"      (uuid \"{uuid.uuid4()}\")",
                        "    )",
                    ]
                )
            body.extend(
                [
                    "    (instances",
                    "      (project \"\"",
                    f"        (path \"/{sheet_uuid}/{symbol_uuid}\"",
                    f"          (reference \"{self._escape_s_expr(schematic_ref)}\")",
                    "          (unit 1)",
                    "        )",
                    "      )",
                    "    )",
                    "  )",
                ]
            )

            for i, (pin_name, net_name) in enumerate(pins):
                if not net_name:
                    continue
                local_pin_y = top_pin_y - i * pin_pitch
                y_pos = y - local_pin_y
                pin_x = x - 10.16
                label_x = pin_x - 17.78
                body.extend(
                    [
                        f"  (wire (pts (xy {label_x:.2f} {y_pos:.2f}) (xy {pin_x:.2f} {y_pos:.2f}))",
                        "    (stroke (width 0.15) (type solid))",
                        f"    (uuid \"{uuid.uuid4()}\")",
                        "  )",
                        f"  (global_label \"{self._escape_s_expr(net_name)}\" (shape input) (at {label_x:.2f} {y_pos:.2f} 180)",
                        "    (effects (font (size 1.27 1.27)) (justify right))",
                        f"    (uuid \"{uuid.uuid4()}\")",
                        "  )",
                    ]
                )

        body.append(")")
        schematic_file.write_text("\n".join(body), encoding="utf-8")
        self._write_project_symbol_library(schematic_file, netlist, comp_pins)

    def _write_project_symbol_library(
        self,
        schematic_file: Path,
        netlist: dict[str, Any],
        comp_pins: dict[str, list[tuple[str, str]]],
    ) -> None:
        library_file = schematic_file.with_name("omnicircuit.kicad_sym")
        table_file = schematic_file.with_name("sym-lib-table")
        library: list[str] = [
            "(kicad_symbol_lib",
            "  (version 20250610)",
            "  (generator \"OmniCircuit AI\")",
            "  (generator_version \"0.1\")",
        ]
        for component in netlist.get("components", []):
            ref = component.get("ref", "")
            if not ref:
                continue
            symbol_id = self._schematic_symbol_id(ref)
            schematic_ref = self._schematic_reference(ref)
            pins = comp_pins.get(ref, [])
            pin_pitch = 2.54
            box_height = max(10.16, len(pins) * pin_pitch + 5.08)
            top_pin_y = ((len(pins) - 1) / 2.0) * pin_pitch
            library.extend(
                [
                    f"  (symbol \"{symbol_id}\" (in_bom yes) (on_board yes)",
                    "    (exclude_from_sim no)",
                    "    (duplicate_pin_numbers_are_jumpers no)",
                    f"    (property \"Reference\" \"{self._escape_s_expr(schematic_ref)}\" (at 0 {box_height / 2 + 2.54:.2f} 0) (effects (font (size 1.27 1.27))))",
                    f"    (property \"Value\" \"{self._escape_s_expr(component.get('value', component.get('part_number', '')))}\" (at 0 {box_height / 2 + 5.08:.2f} 0) (effects (font (size 1.27 1.27))))",
                    "    (property \"Footprint\" \"\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    "    (property \"Datasheet\" \"\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    f"    (property \"Description\" \"{self._escape_s_expr(component.get('reason', 'Generated symbol'))}\" (at 0 0 0) (hide yes) (effects (font (size 1.27 1.27))))",
                    f"    (symbol \"{symbol_id}_0_1\"",
                    f"      (rectangle (start -7.62 {box_height / 2:.2f}) (end 7.62 {-box_height / 2:.2f}) (stroke (width 0.254) (type default)) (fill (type background)))",
                    "    )",
                    f"    (symbol \"{symbol_id}_1_1\"",
                ]
            )
            for index, (pin_name, _) in enumerate(pins):
                y_pos = top_pin_y - index * pin_pitch
                pin_number = str(index + 1)
                library.extend(
                    [
                        f"      (pin passive line (at -10.16 {y_pos:.2f} 0) (length 2.54)",
                        f"        (name \"{self._escape_s_expr(pin_name or pin_number)}\" (effects (font (size 1.0 1.0))))",
                        f"        (number \"{self._escape_s_expr(pin_number)}\" (effects (font (size 1.0 1.0))))",
                        "      )",
                    ]
                )
            library.extend(["    )", "  )"])
        library.append(")")
        library_file.write_text("\n".join(library), encoding="utf-8")
        table_file.write_text(
            "\n".join(
                [
                    "(sym_lib_table",
                    "  (version 7)",
                    "  (lib (name \"OmniCircuit\")(type \"KiCad\")(uri \"${KIPRJMOD}/omnicircuit.kicad_sym\")(options \"\")(descr \"OmniCircuit generated symbols\"))",
                    ")",
                ]
            ),
            encoding="utf-8",
        )

    def _schematic_symbol_id(self, ref: str) -> str:
        return "".join(char if char.isalnum() or char == "_" else "_" for char in ref) or "SYM"

    def _schematic_reference(self, ref: str) -> str:
        safe = "".join(char for char in ref if char.isalnum())
        return safe or "X1"

    def _write_pcbnew_unavailable_stub(self, pcb_file: Path, netlist: dict[str, Any], reason: str) -> None:
        pcb_file.write_text(
            "\n".join(
                [
                    "(kicad_pcb (version 20240108) (generator \"OmniCircuit AI\")",
                    f"  (general (thickness 1.6))",
                    f"  (comment 1 \"pcbnew unavailable: {self._escape_s_expr(reason)}\")",
                    f"  (comment 2 \"Project: {self._escape_s_expr(netlist.get('project_name', 'OmniCircuit AI'))}\")",
                    ")",
                ]
            ),
            encoding="utf-8",
        )

    def _require_kicad_cli(self) -> None:
        if shutil.which(self.kicad_cli) is None:
            raise KiCadAutomationError(
                f"{self.kicad_cli!r} was not found on PATH. Install KiCad or pass the full kicad-cli path."
            )

    async def _run_cli(self, command: list[str]) -> CliResult:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return CliResult(
            command=command,
            returncode=process.returncode,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
        )

    def _vector(self, pcbnew: Any, x_mm: float, y_mm: float) -> Any:
        if hasattr(pcbnew, "VECTOR2I"):
            return pcbnew.VECTOR2I(self._from_mm(pcbnew, x_mm), self._from_mm(pcbnew, y_mm))
        return pcbnew.wxPoint(self._from_mm(pcbnew, x_mm), self._from_mm(pcbnew, y_mm))

    def _from_mm(self, pcbnew: Any, value: float) -> int:
        if hasattr(pcbnew, "FromMM"):
            return int(pcbnew.FromMM(value))
        return int(round(value * MM))

    def _safe_project_name(self, name: str) -> str:
        clean = "".join(char.lower() if char.isalnum() else "_" for char in name).strip("_")
        return clean or "omnicircuit_project"

    def _escape_s_expr(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


async def _async_main(args: argparse.Namespace) -> int:
    service = KiCadAutomationService(kicad_cli=args.kicad_cli)
    artifacts = service.create_project_from_ai_netlist(Path(args.netlist), Path(args.output_root))
    print(json.dumps(asdict(artifacts), indent=2))
    if args.export:
        run = await service.run_manufacturing_pipeline(
            artifacts,
            continue_on_drc_error=args.continue_on_drc_error,
        )
        print(json.dumps(run.to_dict(), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Create KiCad artifacts from AI_Netlist_v1.")
    parser.add_argument("--netlist", default="outputs/phase1/AI_NETLIST_V1.example.json")
    parser.add_argument("--output-root", default="outputs/kicad")
    parser.add_argument("--kicad-cli", default="kicad-cli")
    parser.add_argument("--export", action="store_true", help="Run DRC, Gerber, drill, and position exports.")
    parser.add_argument("--continue-on-drc-error", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
