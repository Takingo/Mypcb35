from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class PCBaiFeedbackAdapter:
    """Prepares KiCad DRC findings as optimization penalties for PCBai.

    The public PCBai repository interface is still expected to evolve, so this
    adapter deliberately returns a plain JSON-compatible payload. A future
    concrete adapter can hand this payload to PCBai's placement/routing solver.
    """

    def build_solver_input(self, drc_report_path: Path) -> dict[str, Any]:
        report = json.loads(drc_report_path.read_text(encoding="utf-8"))
        penalties = report.get("pcbai_constraints", [])
        return {
            "schema": "PCBAI_CONSTRAINT_FEEDBACK_V1",
            "source_schema": report.get("schema"),
            "source": report.get("source"),
            "objective": "minimize_drc_violations",
            "rules": [
                "If category is clearance, spread coordinates around target x/y.",
                "If category is unrouted, route the missing net; use layer change when congestion blocks the direct route.",
                "If category is keepout, evacuate pads/tracks/vias from the protected zone.",
                "If category is courtyard, increase component spacing or regenerate courtyard geometry.",
            ],
            "penalties": penalties,
        }

    def write_solver_input(self, drc_report_path: Path, output_path: Path) -> dict[str, Any]:
        payload = self.build_solver_input(drc_report_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload
