from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netlist_source_normalizer import load_bom_evidence, normalize_design_source


@dataclass(frozen=True)
class DesignEvidenceFinding:
    code: str
    severity: str
    evidence: str


@dataclass(frozen=True)
class DesignEvidenceGateResult:
    ok: bool
    findings: list[DesignEvidenceFinding]

    @property
    def evidence_summary(self) -> str:
        if not self.findings:
            return "Design source evidence gate passed."
        return "; ".join(finding.evidence for finding in self.findings[:6])


def audit_design_evidence_gate(netlist_file: Path, bom_file: Path) -> DesignEvidenceGateResult:
    findings: list[DesignEvidenceFinding] = []

    if not netlist_file.exists():
        return DesignEvidenceGateResult(
            ok=False,
            findings=[
                DesignEvidenceFinding(
                    "NETLIST_MISSING",
                    "blocker",
                    f"AI netlist source not found: {netlist_file}",
                )
            ],
        )

    try:
        netlist = json.loads(netlist_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return DesignEvidenceGateResult(
            ok=False,
            findings=[
                DesignEvidenceFinding(
                    "NETLIST_INVALID_JSON",
                    "blocker",
                    f"AI netlist is not valid JSON: {exc}",
                )
            ],
        )

    schema = netlist.get("schema")
    if schema not in ("AI_Netlist_v1", "AI_NETLIST_V1"):
        findings.append(
            DesignEvidenceFinding(
                "NETLIST_SCHEMA_UNKNOWN",
                "blocker",
                f"Unsupported AI netlist schema: {schema!r}.",
            )
        )

    normalized_netlist = normalize_design_source(netlist, bom_file)
    components = [item for item in normalized_netlist.get("components", []) if isinstance(item, dict)]
    nets = [item for item in normalized_netlist.get("nets", []) if isinstance(item, dict)]
    if not components:
        findings.append(
            DesignEvidenceFinding(
                "NETLIST_EMPTY_COMPONENTS",
                "blocker",
                "AI netlist has no components; local AI output must be reviewed or regenerated.",
            )
        )
    if not nets:
        findings.append(
            DesignEvidenceFinding(
                "NETLIST_EMPTY_NETS",
                "blocker",
                "AI netlist has no nets; PCB/PCBA cannot be trusted as electrically sourced.",
            )
        )

    refs = {str(component.get("ref", "")).strip() for component in components}
    refs.discard("")
    if len(refs) != len(components):
        findings.append(
            DesignEvidenceFinding(
                "NETLIST_DUPLICATE_OR_EMPTY_REFS",
                "blocker",
                "AI netlist contains duplicate or empty component references.",
            )
        )

    critical_missing = _critical_component_evidence_missing(components)
    if critical_missing:
        findings.append(
            DesignEvidenceFinding(
                "CRITICAL_COMPONENT_EVIDENCE_MISSING",
                "blocker",
                "Critical components missing manufacturer/part_number/type evidence: "
                + ", ".join(critical_missing[:12]),
            )
        )

    dangling_refs = _dangling_net_refs(nets, refs)
    if dangling_refs:
        findings.append(
            DesignEvidenceFinding(
                "NET_REFERENCES_UNKNOWN_COMPONENT",
                "blocker",
                "Nets reference components not present in AI netlist: "
                + ", ".join(dangling_refs[:12]),
            )
        )

    bom_evidence = load_bom_evidence(normalized_netlist, bom_file)
    if bom_evidence.raw_text:
        missing_from_bom = [
            str(component.get("part_number", "")).strip()
            for component in components
            if str(component.get("part_number", "")).strip()
            and _part_key(str(component.get("part_number", ""))) not in bom_evidence.part_numbers
            and _is_critical_component(component)
        ]
        if missing_from_bom:
            findings.append(
                DesignEvidenceFinding(
                    "CRITICAL_PART_NOT_IN_BOM",
                    "blocker",
                    "Critical AI netlist parts are not traceable in BOM.csv: "
                    + ", ".join(sorted(set(missing_from_bom))[:12]),
                )
            )

    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    return DesignEvidenceGateResult(ok=blocker_count == 0, findings=findings)


def _critical_component_evidence_missing(components: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for component in components:
        if not _is_critical_component(component):
            continue
        required = ("ref", "type", "manufacturer", "part_number")
        if any(not str(component.get(key, "")).strip() for key in required):
            missing.append(str(component.get("ref", "<unknown>")))
    return missing


def _is_critical_component(component: dict[str, Any]) -> bool:
    text = " ".join(
        str(component.get(key, ""))
        for key in ("ref", "type", "value", "manufacturer", "part_number", "reason")
    ).lower()
    tokens = (
        "dwm",
        "uwb",
        "rf",
        "esp32",
        "mcu",
        "ac",
        "mains",
        "hlk",
        "relay",
        "level",
        "translator",
        "buck",
        "ldo",
        "regulator",
        "fuse",
        "varistor",
        "mosfet",
        "opto",
    )
    return any(token in text for token in tokens)


def _part_key(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())


def _dangling_net_refs(nets: list[dict[str, Any]], refs: set[str]) -> list[str]:
    allowed_virtual_prefixes = ("J", "TP", "ANT")
    dangling: set[str] = set()
    for net in nets:
        for pin in net.get("pins", []):
            ref, _, _pin_name = str(pin).partition(".")
            if not ref or ref in refs:
                continue
            if ref.upper().startswith(allowed_virtual_prefixes):
                continue
            dangling.add(ref)
    return sorted(dangling)
