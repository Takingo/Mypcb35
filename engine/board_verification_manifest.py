from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from design_evidence_gate import audit_design_evidence_gate
from production_model_gate import audit_production_model_gate


@dataclass(frozen=True)
class BoardVerificationManifest:
    schema: str
    generated_at: str
    status: str
    manufacturing_ready: bool
    total_findings: int
    violation_count: int
    unconnected_count: int
    error_count: int
    warning_count: int
    type_counts: dict[str, int]
    source_evidence_pass: bool
    production_model_pass: bool
    kicad_version: str
    pcb_file: str
    pcb_sha256: str
    drc_report_file: str
    drc_report_sha256: str
    netlist_file: str
    netlist_sha256: str
    bom_file: str
    bom_sha256: str
    evidence_summary: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_board_verification_manifest(
    *,
    pcb_file: Path,
    drc_report_file: Path,
    netlist_file: Path,
    bom_file: Path,
) -> BoardVerificationManifest:
    drc = _read_json(drc_report_file)
    violations = list(drc.get("violations") or drc.get("items") or [])
    unconnected = list(drc.get("unconnected_items") or [])
    for item in unconnected:
        if isinstance(item, dict):
            item.setdefault("type", "unconnected_items")
            item.setdefault("severity", "error")

    findings = [item for item in violations + unconnected if isinstance(item, dict)]
    type_counts = Counter(str(item.get("type", "unknown")) for item in findings)
    error_count = sum(1 for item in findings if str(item.get("severity", "")).lower() == "error")
    warning_count = sum(1 for item in findings if str(item.get("severity", "")).lower() == "warning")

    source_gate = audit_design_evidence_gate(netlist_file, bom_file)
    model_gate = audit_production_model_gate(pcb_file)
    total = len(findings)
    ready = total == 0 and source_gate.ok and model_gate.ok
    evidence = []
    if total:
        evidence.append(f"KiCad DRC toplam {total} bulgu: {error_count} error, {warning_count} warning.")
    if not source_gate.ok:
        evidence.append(f"Kaynak kaniti fail: {source_gate.evidence_summary}")
    if not model_gate.ok:
        evidence.append(f"Uretim modeli fail: {model_gate.evidence_summary}")
    if not evidence:
        evidence.append("KiCad DRC temiz, kaynak kaniti ve uretim modeli gecti.")

    return BoardVerificationManifest(
        schema="BOARD_VERIFICATION_MANIFEST_V1",
        generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        status="production_candidate" if ready else "blocked",
        manufacturing_ready=ready,
        total_findings=total,
        violation_count=len(violations),
        unconnected_count=len(unconnected),
        error_count=error_count,
        warning_count=warning_count,
        type_counts=dict(sorted(type_counts.items())),
        source_evidence_pass=source_gate.ok,
        production_model_pass=model_gate.ok,
        kicad_version=str(drc.get("kicad_version", "")),
        pcb_file=str(pcb_file),
        pcb_sha256=_sha256_or_empty(pcb_file),
        drc_report_file=str(drc_report_file),
        drc_report_sha256=_sha256_or_empty(drc_report_file),
        netlist_file=str(netlist_file),
        netlist_sha256=_sha256_or_empty(netlist_file),
        bom_file=str(bom_file),
        bom_sha256=_sha256_or_empty(bom_file),
        evidence_summary=" ".join(evidence),
    )


def write_board_verification_manifest(
    *,
    pcb_file: Path,
    drc_report_file: Path,
    netlist_file: Path,
    bom_file: Path,
    output_file: Path,
    asset_output_file: Path | None = None,
) -> BoardVerificationManifest:
    manifest = build_board_verification_manifest(
        pcb_file=pcb_file,
        drc_report_file=drc_report_file,
        netlist_file=netlist_file,
        bom_file=bom_file,
    )
    _write_json(output_file, manifest.to_dict())
    if asset_output_file is not None:
        _write_json(asset_output_file, manifest.to_dict())
    return manifest


def manifest_gate_failure(manifest_file: Path, *, pcb_file: Path, drc_report_file: Path) -> str | None:
    if not manifest_file.exists():
        return f"Board verification manifest yok: {manifest_file}"
    data = _read_json(manifest_file)
    if data.get("schema") != "BOARD_VERIFICATION_MANIFEST_V1":
        return "Board verification manifest semasi gecersiz."
    if str(data.get("pcb_sha256", "")) != _sha256_or_empty(pcb_file):
        return "Board verification manifest aktif PCB dosyasi ile ayni degil; DRC tekrar kosulmali."
    if str(data.get("drc_report_sha256", "")) != _sha256_or_empty(drc_report_file):
        return "Board verification manifest aktif DRC raporu ile ayni degil; manifest tekrar uretilmeli."
    if bool(data.get("manufacturing_ready", False)):
        return None
    return str(data.get("evidence_summary") or "Board verification manifest uretime hazir degil.")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _sha256_or_empty(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    project = "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
    project_dir = Path("outputs/kicad") / project
    parser = argparse.ArgumentParser(description="Write the strict board verification manifest.")
    parser.add_argument("--pcb-file", default=str(project_dir / f"{project}.kicad_pcb"))
    parser.add_argument("--drc-report-file", default=str(project_dir / "manufacturing" / "drc_report.json"))
    parser.add_argument("--netlist-file", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--bom-file", default="BOM.csv")
    parser.add_argument("--output", default="outputs/engineering/board_verification_manifest.json")
    parser.add_argument("--asset-output", default="assets/generated/board_verification_manifest.json")
    args = parser.parse_args()

    manifest = write_board_verification_manifest(
        pcb_file=Path(args.pcb_file),
        drc_report_file=Path(args.drc_report_file),
        netlist_file=Path(args.netlist_file),
        bom_file=Path(args.bom_file),
        output_file=Path(args.output),
        asset_output_file=Path(args.asset_output) if args.asset_output else None,
    )
    print(json.dumps(manifest.to_dict(), indent=2))
    return 0 if manifest.manufacturing_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
