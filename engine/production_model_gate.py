from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProductionModelFinding:
    code: str
    severity: str
    evidence: str


@dataclass(frozen=True)
class ProductionModelGateResult:
    ok: bool
    findings: list[ProductionModelFinding]

    @property
    def evidence_summary(self) -> str:
        if not self.findings:
            return "Footprint model gate passed."
        return "; ".join(finding.evidence for finding in self.findings[:5])


def audit_production_model_gate(pcb_file: Path) -> ProductionModelGateResult:
    findings: list[ProductionModelFinding] = []
    if not pcb_file.exists():
        return ProductionModelGateResult(
            ok=False,
            findings=[
                ProductionModelFinding(
                    "PCB_MISSING",
                    "blocker",
                    f"PCB file not found: {pcb_file}",
                )
            ],
        )

    text = pcb_file.read_text(encoding="utf-8", errors="ignore")
    if "pcbnew unavailable" in text or "(footprint" not in text:
        findings.append(
            ProductionModelFinding(
                "PCB_STUB",
                "blocker",
                "Active PCB is a stub or does not contain footprint data.",
            )
        )
    if re.search(r'\(footprint\s+""', text):
        refs = _empty_footprint_refs_from_text(text)
        detail = f" ({', '.join(refs[:8])})" if refs else ""
        findings.append(
            ProductionModelFinding(
                "SYNTHETIC_FOOTPRINT",
                "blocker",
                f"PCB contains footprint(s) without a KiCad library identity{detail}.",
            )
        )

    try:
        findings.extend(_audit_with_pcbnew(pcb_file))
    except Exception as exc:
        if not findings:
            findings.append(
                ProductionModelFinding(
                    "MODEL_GATE_UNREADABLE",
                    "blocker",
                    f"Could not inspect PCB production model with KiCad Python: {exc}",
                )
            )

    blocker_count = sum(1 for finding in findings if finding.severity == "blocker")
    return ProductionModelGateResult(ok=blocker_count == 0, findings=findings)


def _audit_with_pcbnew(pcb_file: Path) -> list[ProductionModelFinding]:
    import pcbnew  # type: ignore[import-not-found]

    board = pcbnew.LoadBoard(str(pcb_file))
    findings: list[ProductionModelFinding] = []
    for footprint in board.GetFootprints():
        ref = footprint.GetReference()
        value = footprint.GetValue()
        fpid = footprint.GetFPID()
        item_name = ""
        if hasattr(fpid, "GetLibItemName"):
            item_name = str(fpid.GetLibItemName())
        if not item_name:
            findings.append(
                ProductionModelFinding(
                    "SYNTHETIC_FOOTPRINT",
                    "blocker",
                    f"{ref} ({value}) has no KiCad library footprint identity.",
                )
            )

        pads = list(footprint.Pads())
        if not pads:
            findings.append(
                ProductionModelFinding(
                    "FOOTPRINT_WITHOUT_PADS",
                    "blocker",
                    f"{ref} ({value}) has no pads.",
                )
            )
            continue

        no_net_pads = [pad for pad in pads if not str(pad.GetNetname()).strip()]
        if len(pads) >= 4 and len(no_net_pads) / len(pads) > 0.25:
            findings.append(
                ProductionModelFinding(
                    "UNQUALIFIED_NO_NET_PADS",
                    "blocker",
                    f"{ref} ({value}) has {len(no_net_pads)}/{len(pads)} pads with no net assignment.",
                )
            )
    return findings


def _empty_footprint_refs_from_text(text: str) -> list[str]:
    refs: list[str] = []
    for match in re.finditer(r'\(footprint\s+""(?P<body>.*?)(?=\n\t\(footprint|\n\))', text, re.DOTALL):
        body = match.group("body")
        ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', body)
        if ref_match:
            refs.append(ref_match.group(1))
    return refs
