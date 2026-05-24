from __future__ import annotations

import argparse
import asyncio
import json
import math
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from engine.drc_parser import DrcReport, KiCadDrcParser, write_report
from engine.kicad_automation_service import CliResult, KiCadAutomationService


MM = 1_000_000
RF_NET_NAME = "UWB_RF_50R"


@dataclass(frozen=True)
class OptimizerAction:
    iteration: int
    action_type: str
    target: str
    detail: str


@dataclass(frozen=True)
class OptimizerIteration:
    iteration: int
    violation_count_before: int
    violation_count_after: int | None
    actions: list[OptimizerAction]


@dataclass(frozen=True)
class LayoutOptimizationRun:
    schema: str
    pcb_file: str
    max_iterations: int
    final_violation_count: int
    manufacturing_ready: bool
    iterations: list[OptimizerIteration] = field(default_factory=list)
    export_results: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LayoutOptimizerService:
    """Closed-loop DRC fixer for KiCad board files.

    This is intentionally conservative. It performs deterministic repairs that
    are safe for a generated placeholder board:
    - Same-footprint clearance: shrink placeholder pad geometry while preserving
      DWM3000's mandatory 1.0mm pitch.
    - Cross-footprint clearance: move components apart by a small vector.
    - Unrouted nets: draw simple top-layer Manhattan tracks between two pads.

    It never claims manufacturing readiness unless KiCad DRC returns zero
    normalized violations.
    """

    def __init__(
        self,
        *,
        kicad_cli: str,
        max_iterations: int = 5,
        move_step_mm: float = 2.0,
    ) -> None:
        self.kicad_cli = kicad_cli
        self.max_iterations = max_iterations
        self.move_step_mm = move_step_mm
        self.kicad = KiCadAutomationService(kicad_cli=kicad_cli)

    async def optimize(
        self,
        pcb_file: Path,
        work_dir: Path,
        *,
        status_output: Path,
        export_when_clean: bool = True,
    ) -> LayoutOptimizationRun:
        self._backup_once(pcb_file)
        work_dir.mkdir(parents=True, exist_ok=True)
        iterations: list[OptimizerIteration] = []
        notes: list[str] = []
        final_report = await self._run_and_parse_drc(pcb_file, work_dir, 0)
        final_count = final_report.total_violations

        for iteration in range(1, self.max_iterations + 1):
            if final_count == 0:
                break
            actions = self._apply_repairs(pcb_file, final_report, iteration)
            if not actions:
                notes.append("No deterministic repairs were applicable for remaining DRC items.")
                break
            after_report = await self._run_and_parse_drc(pcb_file, work_dir, iteration)
            iterations.append(
                OptimizerIteration(
                    iteration=iteration,
                    violation_count_before=final_count,
                    violation_count_after=after_report.total_violations,
                    actions=actions,
                )
            )
            if after_report.total_violations >= final_count:
                notes.append(
                    f"Iteration {iteration} did not reduce DRC count "
                    f"({final_count} -> {after_report.total_violations}). Stopping to avoid oscillation."
                )
                final_report = after_report
                final_count = after_report.total_violations
                break
            final_report = after_report
            final_count = after_report.total_violations

        manufacturing_ready = final_count == 0
        export_results: dict[str, Any] = {}
        if manufacturing_ready and export_when_clean:
            export_results = await self._export_manufacturing(pcb_file, work_dir)

        run = LayoutOptimizationRun(
            schema="LAYOUT_OPTIMIZATION_RUN_V1",
            pcb_file=str(pcb_file),
            max_iterations=self.max_iterations,
            final_violation_count=final_count,
            manufacturing_ready=manufacturing_ready,
            iterations=iterations,
            export_results=export_results,
            notes=notes,
        )
        status_output.parent.mkdir(parents=True, exist_ok=True)
        status_output.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")
        return run

    def _apply_repairs(self, pcb_file: Path, report: DrcReport, iteration: int) -> list[OptimizerAction]:
        pcbnew = self._import_pcbnew()
        board = pcbnew.LoadBoard(str(pcb_file))
        footprints = {footprint.GetReference(): footprint for footprint in board.GetFootprints()}
        actions: list[OptimizerAction] = []

        same_footprint_refs = self._same_footprint_clearance_refs(report)
        for ref in sorted(same_footprint_refs):
            footprint = footprints.get(ref)
            if footprint is None:
                continue
            changed = self._shrink_placeholder_pads(pcbnew, footprint)
            if changed:
                actions.append(
                    OptimizerAction(
                        iteration=iteration,
                        action_type="shrink_placeholder_pads",
                        target=ref,
                        detail="Reduced generated pad size to satisfy clearance while preserving pad pitch.",
                    )
                )

        for violation in report.violations:
            if violation.category == "silkscreen":
                actions.extend(self._repair_silkscreen(footprints, violation, iteration))
                continue
            if violation.category != "clearance":
                continue
            refs = sorted({location.component for location in violation.locations if location.component})
            if len(refs) < 2:
                continue
            moved = self._move_components_apart(pcbnew, footprints, refs, violation)
            actions.extend(
                OptimizerAction(iteration, "move_component", target, detail)
                for target, detail in moved
            )

        unrouted_actions = self._route_unrouted_nets(pcbnew, board, report, iteration)
        actions.extend(unrouted_actions)
        pcbnew.SaveBoard(str(pcb_file), board)
        return actions

    def _repair_silkscreen(
        self,
        footprints: dict[str, Any],
        violation: Any,
        iteration: int,
    ) -> list[OptimizerAction]:
        actions: list[OptimizerAction] = []
        refs = sorted({location.component for location in violation.locations if location.component})
        for ref in refs:
            footprint = footprints.get(ref)
            if footprint is None:
                continue
            changed = False
            for field_getter in ("Reference", "Value"):
                if not hasattr(footprint, field_getter):
                    continue
                field = getattr(footprint, field_getter)()
                if hasattr(field, "SetVisible"):
                    field.SetVisible(False)
                    changed = True
            if changed:
                actions.append(
                    OptimizerAction(
                        iteration=iteration,
                        action_type="hide_silkscreen_text",
                        target=ref,
                        detail=f"Hid reference/value text for {violation.id} to clear solder mask/copper overlap.",
                    )
                )
        return actions

    def _same_footprint_clearance_refs(self, report: DrcReport) -> set[str]:
        refs: set[str] = set()
        for violation in report.violations:
            if violation.category != "clearance":
                continue
            components = {location.component for location in violation.locations if location.component}
            if len(components) == 1:
                refs.update(component for component in components if component)
        return refs

    def _shrink_placeholder_pads(self, pcbnew: Any, footprint: Any) -> bool:
        ref = footprint.GetReference()
        if ref == "U2":
            target_x_mm = 0.55
            target_y_mm = 0.55
        elif ref.startswith(("U", "K", "OK", "Q")):
            target_x_mm = 0.30
            target_y_mm = 0.30
        else:
            target_x_mm = 0.45
            target_y_mm = 0.45

        changed = False
        for pad in footprint.Pads():
            size = pad.GetSize()
            new_size = self._vector(pcbnew, min(self._to_mm(pcbnew, size.x), target_x_mm), min(self._to_mm(pcbnew, size.y), target_y_mm))
            if new_size.x != size.x or new_size.y != size.y:
                pad.SetSize(new_size)
                changed = True
        return changed

    def _move_components_apart(
        self,
        pcbnew: Any,
        footprints: dict[str, Any],
        refs: list[str],
        violation: Any,
    ) -> list[tuple[str, str]]:
        if len(refs) < 2:
            return []
        first = footprints.get(refs[0])
        second = footprints.get(refs[1])
        if first is None or second is None:
            return []

        first_pos = first.GetPosition()
        second_pos = second.GetPosition()
        dx = second_pos.x - first_pos.x
        dy = second_pos.y - first_pos.y
        length = math.hypot(dx, dy) or 1.0
        step = self._from_mm(pcbnew, self.move_step_mm)
        move_x = int(round(step * dx / length))
        move_y = int(round(step * dy / length))
        second.SetPosition(self._vector_raw(pcbnew, second_pos.x + move_x, second_pos.y + move_y))
        return [(refs[1], f"Moved away from {refs[0]} by {self.move_step_mm:.1f}mm near {violation.id}.")]

    def _route_unrouted_nets(self, pcbnew: Any, board: Any, report: DrcReport, iteration: int) -> list[OptimizerAction]:
        if not any(violation.category == "unrouted" for violation in report.violations):
            return []
        actions: list[OptimizerAction] = []
        pads_by_net = self._pads_by_net(board)
        for net_name, pads in pads_by_net.items():
            if len(pads) < 2:
                continue
            if net_name == RF_NET_NAME:
                if not self._net_has_track(board, net_name):
                    self._add_track(pcbnew, board, pads[0], pads[1], pcbnew.F_Cu, 0.35)
                    actions.append(OptimizerAction(iteration, "route_rf_top_no_via", net_name, "Routed RF net on top layer without vias."))
            else:
                routed_count = self._route_star_topology(pcbnew, board, pads, pcbnew.F_Cu, 0.25)
                if routed_count:
                    actions.append(
                        OptimizerAction(
                            iteration,
                            "route_top_star",
                            net_name,
                            f"Routed {routed_count} top-layer segment pair(s) to connect multi-pad net.",
                        )
                    )
        return actions

    def _route_star_topology(self, pcbnew: Any, board: Any, pads: list[Any], layer: int, width_mm: float) -> int:
        anchor = pads[0]
        count = 0
        for pad in pads[1:]:
            self._add_manhattan_track(pcbnew, board, anchor, pad, layer, width_mm)
            count += 1
        return count

    def _pads_by_net(self, board: Any) -> dict[str, list[Any]]:
        pads_by_net: dict[str, list[Any]] = {}
        for footprint in board.GetFootprints():
            for pad in footprint.Pads():
                net_name = pad.GetNetname()
                if net_name:
                    pads_by_net.setdefault(net_name, []).append(pad)
        return pads_by_net

    def _net_has_track(self, board: Any, net_name: str) -> bool:
        for track in board.GetTracks():
            if hasattr(track, "GetNetname") and track.GetNetname() == net_name:
                return True
        return False

    def _add_manhattan_track(self, pcbnew: Any, board: Any, start_pad: Any, end_pad: Any, layer: int, width_mm: float) -> None:
        start = start_pad.GetPosition()
        end = end_pad.GetPosition()
        corner = self._vector_raw(pcbnew, end.x, start.y)
        self._add_segment(pcbnew, board, start_pad, start, corner, layer, width_mm)
        self._add_segment(pcbnew, board, start_pad, corner, end, layer, width_mm)

    def _add_track(self, pcbnew: Any, board: Any, start_pad: Any, end_pad: Any, layer: int, width_mm: float) -> None:
        self._add_segment(pcbnew, board, start_pad, start_pad.GetPosition(), end_pad.GetPosition(), layer, width_mm)

    def _add_segment(self, pcbnew: Any, board: Any, source_pad: Any, start: Any, end: Any, layer: int, width_mm: float) -> None:
        track = pcbnew.PCB_TRACK(board)
        track.SetStart(start)
        track.SetEnd(end)
        track.SetLayer(layer)
        track.SetWidth(self._from_mm(pcbnew, width_mm))
        if hasattr(track, "SetNet"):
            track.SetNet(source_pad.GetNet())
        elif hasattr(track, "SetNetCode"):
            track.SetNetCode(source_pad.GetNetCode())
        board.Add(track)

    async def _run_and_parse_drc(self, pcb_file: Path, work_dir: Path, iteration: int) -> DrcReport:
        raw_report = work_dir / f"kicad_drc_iteration_{iteration}.json"
        normalized_report = work_dir / f"DRC_REPORT_V1_iteration_{iteration}.json"
        await self.kicad.run_drc(pcb_file, raw_report)
        return write_report(raw_report, normalized_report)

    async def _export_manufacturing(self, pcb_file: Path, work_dir: Path) -> dict[str, Any]:
        gerber = await self.kicad.export_gerber(pcb_file, work_dir / "gerber")
        drill = await self.kicad.export_drill(pcb_file, work_dir / "drill")
        position = await self.kicad.export_position(pcb_file, work_dir / "position")
        return {
            "gerber": gerber.ok,
            "drill": drill.ok,
            "position": position.ok,
            "gerber_stdout": gerber.stdout,
            "drill_stdout": drill.stdout,
            "position_stdout": position.stdout,
        }

    def _backup_once(self, pcb_file: Path) -> None:
        backup = pcb_file.with_suffix(".before_optimizer.kicad_pcb")
        if not backup.exists():
            shutil.copy2(pcb_file, backup)

    def _import_pcbnew(self) -> Any:
        import pcbnew  # type: ignore[import-not-found]

        return pcbnew

    def _from_mm(self, pcbnew: Any, value: float) -> int:
        if hasattr(pcbnew, "FromMM"):
            return int(pcbnew.FromMM(value))
        return int(round(value * MM))

    def _to_mm(self, pcbnew: Any, value: int) -> float:
        if hasattr(pcbnew, "ToMM"):
            return float(pcbnew.ToMM(value))
        return value / MM

    def _vector(self, pcbnew: Any, x_mm: float, y_mm: float) -> Any:
        return self._vector_raw(pcbnew, self._from_mm(pcbnew, x_mm), self._from_mm(pcbnew, y_mm))

    def _vector_raw(self, pcbnew: Any, x: int, y: int) -> Any:
        if hasattr(pcbnew, "VECTOR2I"):
            return pcbnew.VECTOR2I(int(x), int(y))
        return pcbnew.wxPoint(int(x), int(y))


async def _async_main(args: argparse.Namespace) -> int:
    service = LayoutOptimizerService(
        kicad_cli=args.kicad_cli,
        max_iterations=args.max_iterations,
        move_step_mm=args.move_step_mm,
    )
    run = await service.optimize(
        Path(args.pcb_file),
        Path(args.work_dir),
        status_output=Path(args.status_output),
        export_when_clean=not args.no_export_when_clean,
    )
    print(json.dumps(run.to_dict(), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Closed-loop KiCad DRC optimizer.")
    parser.add_argument("--pcb-file", required=True)
    parser.add_argument("--work-dir", default="outputs/phase4")
    parser.add_argument("--status-output", default="outputs/phase4/layout_optimization_status.json")
    parser.add_argument("--kicad-cli", default="kicad-cli")
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument("--move-step-mm", type=float, default=2.0)
    parser.add_argument("--no-export-when-clean", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
