from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DRC_REPORT_SCHEMA = "DRC_REPORT_V1"


@dataclass(frozen=True)
class DrcLocation:
    x: float | None
    y: float | None
    layer: str | None
    item: str
    component: str | None
    uuid: str | None


@dataclass(frozen=True)
class DrcViolation:
    id: str
    category: str
    raw_type: str
    severity: str
    description: str
    locations: list[DrcLocation]
    repair_hint: str
    pcbai_penalty: dict[str, Any]


@dataclass(frozen=True)
class DrcReport:
    schema: str
    source: str
    kicad_version: str
    coordinate_units: str
    total_violations: int
    summary_by_category: dict[str, int]
    summary_by_severity: dict[str, int]
    violations: list[DrcViolation]
    pcbai_constraints: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KiCadDrcParser:
    def parse_file(self, report_path: Path) -> DrcReport:
        data = json.loads(report_path.read_text(encoding="utf-8"))
        return self.parse(data)

    def parse(self, data: dict[str, Any]) -> DrcReport:
        violations = [
            self._parse_violation(index, violation)
            for index, violation in enumerate(data.get("violations", []), start=1)
        ]
        next_index = len(violations) + 1
        violations.extend(
            self._parse_unconnected_item(index, item)
            for index, item in enumerate(data.get("unconnected_items", []), start=next_index)
        )
        category_counts = Counter(violation.category for violation in violations)
        severity_counts = Counter(violation.severity for violation in violations)
        return DrcReport(
            schema=DRC_REPORT_SCHEMA,
            source=data.get("source", ""),
            kicad_version=data.get("kicad_version", ""),
            coordinate_units=data.get("coordinate_units", "mm"),
            total_violations=len(violations),
            summary_by_category=dict(sorted(category_counts.items())),
            summary_by_severity=dict(sorted(severity_counts.items())),
            violations=violations,
            pcbai_constraints=[violation.pcbai_penalty for violation in violations],
        )

    def _parse_violation(self, index: int, violation: dict[str, Any]) -> DrcViolation:
        raw_type = violation.get("type", "unknown")
        description = violation.get("description", "")
        category = self._category(raw_type, description)
        locations = [self._parse_location(item) for item in violation.get("items", [])]
        return DrcViolation(
            id=f"DRC-{index:04d}",
            category=category,
            raw_type=raw_type,
            severity=violation.get("severity", "unknown"),
            description=description,
            locations=locations,
            repair_hint=self._repair_hint(category),
            pcbai_penalty=self._pcbai_penalty(category, raw_type, description, locations),
        )

    def _parse_unconnected_item(self, index: int, item: dict[str, Any]) -> DrcViolation:
        location = self._parse_location(item)
        return DrcViolation(
            id=f"DRC-{index:04d}",
            category="unrouted",
            raw_type="unconnected",
            severity=item.get("severity", "error"),
            description=item.get("description", "Unrouted or unconnected item"),
            locations=[location],
            repair_hint=self._repair_hint("unrouted"),
            pcbai_penalty=self._pcbai_penalty("unrouted", "unconnected", item.get("description", ""), [location]),
        )

    def _parse_location(self, item: dict[str, Any]) -> DrcLocation:
        description = item.get("description", "")
        pos = item.get("pos", {})
        return DrcLocation(
            x=pos.get("x"),
            y=pos.get("y"),
            layer=self._extract_layer(description),
            item=description,
            component=self._extract_component(description),
            uuid=item.get("uuid"),
        )

    def _category(self, raw_type: str, description: str) -> str:
        text = f"{raw_type} {description}".lower()
        if "unrouted" in text or "unconnected" in text:
            return "unrouted"
        if "clearance" in text:
            return "clearance"
        if "courtyard" in text:
            return "courtyard"
        if "keepout" in text or "not allowed" in text:
            return "keepout"
        if "hole" in text or "drill" in text:
            return "drill"
        if "silk" in text or "silkscreen" in text:
            return "silkscreen"
        return "other"

    def _repair_hint(self, category: str) -> str:
        hints = {
            "clearance": "Move one of the conflicting items away from the shared coordinate until clearance is above the active netclass threshold.",
            "unrouted": "Route the missing net; if congestion remains, try a layer change and via insertion outside RF keepouts.",
            "courtyard": "Increase placement spacing or regenerate the footprint courtyard.",
            "keepout": "Move pads/tracks/vias out of the keepout zone or resize the keepout to the intended protected area.",
            "drill": "Increase hole-to-copper clearance or adjust via/drill size.",
            "silkscreen": "Move or hide reference/value text so it no longer overlaps solder mask or copper.",
            "other": "Inspect the item pair and map it to a concrete placement/routing constraint.",
        }
        return hints.get(category, hints["other"])

    def _pcbai_penalty(
        self,
        category: str,
        raw_type: str,
        description: str,
        locations: list[DrcLocation],
    ) -> dict[str, Any]:
        centroid = self._centroid(locations)
        penalty = {
            "source": "kicad_drc",
            "category": category,
            "raw_type": raw_type,
            "weight": self._penalty_weight(category),
            "target": {
                "x": centroid.get("x"),
                "y": centroid.get("y"),
                "units": "mm",
                "components": sorted({location.component for location in locations if location.component}),
                "layers": sorted({location.layer for location in locations if location.layer}),
            },
            "action": self._pcbai_action(category),
            "description": description,
        }
        return penalty

    def _penalty_weight(self, category: str) -> int:
        return {
            "clearance": 100,
            "unrouted": 120,
            "keepout": 110,
            "courtyard": 60,
            "drill": 90,
            "silkscreen": 20,
            "other": 40,
        }.get(category, 40)

    def _pcbai_action(self, category: str) -> str:
        return {
            "clearance": "spread_coordinates",
            "unrouted": "route_missing_net_or_change_layer",
            "keepout": "evacuate_keepout",
            "courtyard": "increase_component_spacing",
            "drill": "increase_drill_clearance",
            "silkscreen": "move_or_hide_silkscreen_text",
            "other": "inspect_and_penalize_overlap",
        }.get(category, "inspect_and_penalize_overlap")

    def _centroid(self, locations: list[DrcLocation]) -> dict[str, float | None]:
        xs = [location.x for location in locations if location.x is not None]
        ys = [location.y for location in locations if location.y is not None]
        return {
            "x": sum(xs) / len(xs) if xs else None,
            "y": sum(ys) / len(ys) if ys else None,
        }

    def _extract_layer(self, description: str) -> str | None:
        match = re.search(r"\bon\s+([A-Za-z0-9_.+-]+)", description)
        return match.group(1) if match else None

    def _extract_component(self, description: str) -> str | None:
        match = re.search(r"\bof\s+([A-Z]+[0-9A-Z-]*)\b", description)
        return match.group(1) if match else None


def write_report(input_path: Path, output_path: Path) -> DrcReport:
    report = KiCadDrcParser().parse_file(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert KiCad DRC JSON to DRC_REPORT_V1.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="outputs/phase3/DRC_REPORT_V1.json")
    args = parser.parse_args()
    report = write_report(Path(args.input), Path(args.output))
    print(json.dumps({
        "schema": report.schema,
        "total_violations": report.total_violations,
        "summary_by_category": report.summary_by_category,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
