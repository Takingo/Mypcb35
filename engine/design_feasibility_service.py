from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BOARD_WIDTH_MM = 130.0
DEFAULT_BOARD_HEIGHT_MM = 46.0
MAX_PCB_MOUNTED_FOR_FIXED_130X46 = 120
MAX_ROUTING_UTILIZATION = 0.82

NON_PCB_TYPES = {"virtual_module"}
OPTIONAL_TYPES = {"test_point", "led"}
RISK_TYPES = {"ac_dc", "relay", "uwb_module", "antenna", "socket", "connector"}

AREA_BY_TYPE_MM2 = {
    "ac_dc": 900.0,
    "relay": 420.0,
    "socket": 360.0,
    "uwb_module": 90.0,
    "antenna": 220.0,
    "connector": 120.0,
    "fuse": 160.0,
    "varistor": 180.0,
    "buck": 70.0,
    "ldo": 35.0,
    "level_shifter": 30.0,
    "ic": 70.0,
    "optocoupler": 90.0,
    "n_mosfet": 18.0,
    "diode": 28.0,
    "flyback_diode": 45.0,
    "ferrite_bead": 12.0,
    "inductor": 160.0,
    "crystal": 22.0,
    "battery": 320.0,
    "switch": 70.0,
    "test_point": 16.0,
    "led": 20.0,
    "resistor": 12.0,
    "capacitor": 12.0,
    "component": 55.0,
}


@dataclass(frozen=True)
class FeasibilityAction:
    id: str
    label: str
    consequence: str


@dataclass(frozen=True)
class DesignFeasibilityReport:
    schema: str
    generated_at: str
    status: str
    board_size_mm: tuple[float, float]
    board_area_mm2: float
    pcb_mounted_count: int
    total_component_count: int
    estimated_component_area_mm2: float
    estimated_routing_utilization: float
    fixed_board_constraint: bool
    high_risk_blocks: dict[str, int]
    optional_reduction_candidates: dict[str, list[str]]
    blocker_summary: str
    recommended_actions: list[FeasibilityAction]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DesignFeasibilityService:
    """Pre-KiCad feasibility gate for real-world PCB generation.

    This is deliberately conservative. It does not silently override a user's
    mechanical constraint; it reports when the requested electrical scope and
    board envelope are physically inconsistent.
    """

    def audit(self, netlist_file: Path, *, output: Path | None = None) -> DesignFeasibilityReport:
        data = json.loads(netlist_file.read_text(encoding="utf-8"))
        components = list(data.get("components") or [])
        width, height = self._board_size_from_netlist(data)
        board_area = round(width * height, 2)
        pcb_components = [c for c in components if self._is_pcb_mounted(c)]
        component_area = round(sum(self._component_area(c) for c in pcb_components), 2)
        utilization = round(component_area / board_area, 3) if board_area else 999.0
        fixed_board = self._has_fixed_board_constraint(data)
        high_risk = self._count_high_risk_blocks(pcb_components)
        optional = self._optional_candidates(pcb_components)
        status = self._status(
            width=width,
            height=height,
            pcb_mounted_count=len(pcb_components),
            utilization=utilization,
            fixed_board=fixed_board,
        )
        report = DesignFeasibilityReport(
            schema="DESIGN_FEASIBILITY_V1",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            status=status,
            board_size_mm=(width, height),
            board_area_mm2=board_area,
            pcb_mounted_count=len(pcb_components),
            total_component_count=len(components),
            estimated_component_area_mm2=component_area,
            estimated_routing_utilization=utilization,
            fixed_board_constraint=fixed_board,
            high_risk_blocks=high_risk,
            optional_reduction_candidates=optional,
            blocker_summary=self._summary(status, len(pcb_components), width, height, utilization, fixed_board),
            recommended_actions=self._actions(status, fixed_board),
        )
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    def _board_size_from_netlist(self, data: dict[str, Any]) -> tuple[float, float]:
        for key in ("board_size_mm", "board_dimensions_mm"):
            raw = data.get(key)
            parsed = self._parse_size(raw)
            if parsed is not None:
                return parsed
        prompt = str(data.get("source_prompt", ""))
        parsed = self._parse_board_size_text(prompt)
        if parsed is not None:
            return parsed
        return DEFAULT_BOARD_WIDTH_MM, DEFAULT_BOARD_HEIGHT_MM

    def _parse_size(self, raw: Any) -> tuple[float, float] | None:
        if isinstance(raw, dict):
            width = raw.get("width") or raw.get("w")
            height = raw.get("height") or raw.get("h")
            if width and height:
                return float(width), float(height)
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            return float(raw[0]), float(raw[1])
        text = str(raw or "")
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*mm?\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*mm", text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))
        return None

    def _parse_board_size_text(self, text: str) -> tuple[float, float] | None:
        context_terms = ("board", "pcb", "boyut", "kart")
        for line in text.splitlines():
            lowered = line.lower()
            if any(term in lowered for term in context_terms):
                parsed = self._parse_size(line)
                if parsed is not None:
                    return parsed
        return self._parse_size(text)

    def _has_fixed_board_constraint(self, data: dict[str, Any]) -> bool:
        prompt = str(data.get("source_prompt", "")).lower()
        fixed_terms = [
            "board boyutu değişmez",
            "board boyutu degismez",
            "sabit, genişletilmez",
            "sabit, genisletilmez",
            "değiştirme",
            "degistirme",
        ]
        return any(term in prompt for term in fixed_terms)

    def _is_pcb_mounted(self, component: dict[str, Any]) -> bool:
        ctype = str(component.get("type", "")).lower()
        footprint = str(component.get("footprint", "")).lower()
        return ctype not in NON_PCB_TYPES and footprint != "not_pcb_mounted"

    def _component_area(self, component: dict[str, Any]) -> float:
        ctype = str(component.get("type", "component")).lower()
        return AREA_BY_TYPE_MM2.get(ctype, AREA_BY_TYPE_MM2["component"])

    def _count_high_risk_blocks(self, components: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for component in components:
            ctype = str(component.get("type", "")).lower()
            if ctype in RISK_TYPES:
                counts[ctype] = counts.get(ctype, 0) + 1
        return counts

    def _optional_candidates(self, components: list[dict[str, Any]]) -> dict[str, list[str]]:
        candidates: dict[str, list[str]] = {}
        for component in components:
            ref = str(component.get("ref", ""))
            ctype = str(component.get("type", "")).lower()
            if ctype in OPTIONAL_TYPES or self._looks_optional_connector(ref, component):
                candidates.setdefault(ctype or "component", []).append(ref)
        return {key: refs[:40] for key, refs in sorted(candidates.items()) if refs}

    def _looks_optional_connector(self, ref: str, component: dict[str, Any]) -> bool:
        if str(component.get("type", "")).lower() != "connector":
            return False
        if ref in {"J1", "J1_AC", "J1_USB", "J2", "ANT1", "J3", "J4", "J18"}:
            return False
        return ref.startswith("J")

    def _status(
        self,
        *,
        width: float,
        height: float,
        pcb_mounted_count: int,
        utilization: float,
        fixed_board: bool,
    ) -> str:
        if fixed_board and (
            (width <= 130.0 and height <= 46.0 and pcb_mounted_count > MAX_PCB_MOUNTED_FOR_FIXED_130X46)
            or utilization > MAX_ROUTING_UTILIZATION
        ):
            return "review"
        if utilization > MAX_ROUTING_UTILIZATION:
            return "blocked"
        if utilization > 0.65:
            return "review"
        return "pass"

    def _summary(self, status: str, count: int, width: float, height: float, utilization: float, fixed_board: bool) -> str:
        fixed = "fixed" if fixed_board else "flexible"
        if status == "blocked":
            return (
                f"{count} PCB-mounted components exceed the practical envelope for a "
                f"{width:.0f}x{height:.0f}mm {fixed} board; estimated utilization={utilization:.2f}."
            )
        if status == "review":
            return (
                f"{count} PCB-mounted components are dense for {width:.0f}x{height:.0f}mm; "
                f"estimated utilization={utilization:.2f}, engineering review required."
            )
        return f"{count} PCB-mounted components fit the coarse feasibility gate for {width:.0f}x{height:.0f}mm."

    def _actions(self, status: str, fixed_board: bool) -> list[FeasibilityAction]:
        if status != "blocked":
            return []
        actions = [
            FeasibilityAction(
                id="reduce_scope",
                label="Reduce optional scope",
                consequence="Remove optional test points, debug headers/connectors, and noncritical LEDs before rerun.",
            ),
            FeasibilityAction(
                id="split_board",
                label="Split into boards",
                consequence="Separate AC/relay power from RF/logic so isolation and RF constraints can both be met.",
            ),
        ]
        if not fixed_board:
            actions.insert(
                0,
                FeasibilityAction(
                    id="allow_larger_board",
                    label="Allow larger PCB",
                    consequence="Increase board area and keep the same electrical scope.",
                ),
            )
        else:
            actions.append(
                FeasibilityAction(
                    id="override_board_size",
                    label="Override fixed PCB size",
                    consequence="Requires explicit human approval because the user input says the board must not grow.",
                )
            )
        return actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PCB design feasibility before KiCad placement.")
    parser.add_argument("--netlist-file", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--output", default="assets/generated/design_feasibility_report.json")
    args = parser.parse_args()
    report = DesignFeasibilityService().audit(Path(args.netlist_file), output=Path(args.output))
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    return 0 if report.status in {"pass", "review"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
