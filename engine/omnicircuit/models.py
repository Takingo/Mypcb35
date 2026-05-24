from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class BomItem:
    reference: str
    quantity: int
    value: str
    manufacturer: str
    part_number: str
    package: str
    notes: str


@dataclass(frozen=True)
class ProjectInputs:
    schematic_text: str
    pcb_notes_text: str
    bom_items: list[BomItem]


@dataclass(frozen=True)
class ValidationCheck:
    category: str
    requirement: str
    status: str
    evidence: str
    recommendation: str


@dataclass(frozen=True)
class DesignArtifact:
    name: str
    path: str
    status: str
    description: str


@dataclass(frozen=True)
class AnalysisResult:
    project_id: str
    project_name: str
    generated_at: str
    overall_status: str
    checks: list[ValidationCheck] = field(default_factory=list)
    artifacts: list[DesignArtifact] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
