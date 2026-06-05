from __future__ import annotations

import argparse
import json
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
sys.path.append(str(Path(__file__).parent))

from board_verification_manifest import manifest_gate_failure
from design_evidence_gate import audit_design_evidence_gate
from production_model_gate import audit_production_model_gate


DEFAULT_PROJECT = "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"


@dataclass(frozen=True)
class ReadinessCheck:
    id: str
    domain: str
    status: str
    severity: str
    evidence: str
    required_action: str


@dataclass(frozen=True)
class EngineeringReadinessReport:
    schema: str
    generated_at: str
    overall_status: str
    readiness_percent: int
    summary: str
    checks: list[ReadinessCheck]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EngineeringReadinessService:
    """Audits whether the generated artifacts are truly production credible.

    DRC=0 is necessary but not sufficient. This report keeps the app honest by
    checking schematic symbol binding, PCB artifact consistency, simulation
    evidence, PCBA handoff files, and fabrication packaging before claiming a
    design is ready for real manufacturing.
    """

    def audit(
        self,
        *,
        schematic_file: Path,
        erc_report_file: Path,
        pcb_file: Path,
        backup_pcb_file: Path,
        bom_file: Path,
        netlist_file: Path,
        layout_status_file: Path,
        drc_report_file: Path,
        verification_manifest_file: Path,
        fabrication_package_file: Path,
        production_zip: Path,
        output_path: Path,
        asset_output: Path | None,
    ) -> EngineeringReadinessReport:
        checks = [
            self._check_bom(bom_file),
            self._check_design_evidence(netlist_file, bom_file),
            self._check_schematic(schematic_file, erc_report_file),
            self._check_current_pcb(pcb_file, backup_pcb_file),
            self._check_production_model(pcb_file),
            self._check_drc_consistency(layout_status_file, pcb_file, drc_report_file, verification_manifest_file),
            self._check_simulation_evidence(),
            self._check_pcba_evidence(fabrication_package_file, layout_status_file, pcb_file, drc_report_file, verification_manifest_file),
            self._check_fabrication_zip(production_zip, layout_status_file, pcb_file, drc_report_file, verification_manifest_file),
        ]
        report = self._build_report(checks)
        self._write_json(report, output_path)
        if asset_output is not None:
            self._write_json(report, asset_output)
        print(report.summary)
        return report

    def _check_bom(self, bom_file: Path) -> ReadinessCheck:
        if not bom_file.exists():
            return self._fail("BOM_SOURCE", "bom", "blocker", "BOM.csv bulunamadi.", "BOM dosyasini projeye ekle.")
        text = bom_file.read_text(encoding="utf-8", errors="ignore").lower()
        required = ["esp32", "dwm3000", "hlk-5m05", "txb0104", "sn74lvc1t45"]
        missing = [part for part in required if part not in text]
        if missing:
            return self._fail(
                "BOM_SOURCE",
                "bom",
                "blocker",
                f"BOM kritik parcalari eksik gosteriyor: {', '.join(missing)}.",
                "Eksik MPN ve paket bilgilerini BOM'a ekle.",
            )
        return self._pass("BOM_SOURCE", "bom", "BOM kritik komponentleri iceriyor.")

    def _check_design_evidence(self, netlist_file: Path, bom_file: Path) -> ReadinessCheck:
        evidence_gate = audit_design_evidence_gate(netlist_file, bom_file)
        if evidence_gate.ok:
            return self._pass("DESIGN_SOURCE_EVIDENCE", "source", "AI netlist komponent/net/BOM izlenebilirlik kapisini gecti.")
        return self._fail(
            "DESIGN_SOURCE_EVIDENCE",
            "source",
            "blocker",
            evidence_gate.evidence_summary,
            "Gemma4/local AI ciktisini yeniden uret veya eksik komponent/net/BOM kanitlarini kullanicidan iste.",
        )

    def _check_schematic(self, schematic_file: Path, erc_report_file: Path) -> ReadinessCheck:
        if not schematic_file.exists():
            return self._fail("SCHEMATIC_SYMBOLS", "schematic", "blocker", ".kicad_sch bulunamadi.", "Gercek KiCad sematik dosyasi uret.")
        text = schematic_file.read_text(encoding="utf-8", errors="ignore")
        has_symbols = "(symbol " in text
        uses_text_boxes = "(text_box" in text
        if not has_symbols or uses_text_boxes:
            return self._fail(
                "SCHEMATIC_SYMBOLS",
                "schematic",
                "blocker",
                "Sematik text_box/global_label taslagi; gercek symbol instance ve pin ERC baglantisi yok.",
                "KiCad symbol library bagla, symbol-footprint eslestirmesi yap ve ERC kos.",
            )
        if not erc_report_file.exists():
            return self._fail(
                "SCHEMATIC_SYMBOLS",
                "schematic",
                "blocker",
                "Sematik symbol instance iceriyor ancak ERC raporu yok.",
                "kicad-cli sch erc calistir ve raporu uret.",
            )
        erc = json.loads(erc_report_file.read_text(encoding="utf-8"))
        violations = []
        for sheet in erc.get("sheets", []):
            if isinstance(sheet, dict):
                violations.extend(sheet.get("violations", []))
        if violations:
            return self._fail(
                "SCHEMATIC_SYMBOLS",
                "schematic",
                "blocker",
                f"Sematik KiCad tarafindan yukleniyor ama ERC {len(violations)} ihlal buldu.",
                "Pin-wire/global label baglantilarini ve sembol pin modellerini duzelt.",
            )
        return self._pass("SCHEMATIC_SYMBOLS", "schematic", "Sematik gercek KiCad symbol instance'lari iceriyor ve ERC temiz.")

    def _check_current_pcb(self, pcb_file: Path, backup_pcb_file: Path) -> ReadinessCheck:
        if not pcb_file.exists():
            return self._fail("PCB_ARTIFACT", "pcb", "blocker", "Aktif .kicad_pcb bulunamadi.", "PCB dosyasini yeniden uret.")
        text = pcb_file.read_text(encoding="utf-8", errors="ignore")
        if "pcbnew unavailable" in text or "(footprint" not in text:
            backup_note = f" Yedek mevcut: {backup_pcb_file}" if backup_pcb_file.exists() else " Yedek board bulunamadi."
            return self._fail(
                "PCB_ARTIFACT",
                "pcb",
                "blocker",
                f"Aktif PCB dosyasi stub veya footprintsiz gorunuyor.{backup_note}",
                "KiCad Python ortaminda board'u yeniden uret ve aktif .kicad_pcb dosyasini gercek footprint'lerle degistir.",
            )
        return self._pass("PCB_ARTIFACT", "pcb", "Aktif PCB dosyasi footprint verisi iceriyor.")

    def _check_production_model(self, pcb_file: Path) -> ReadinessCheck:
        model_gate = audit_production_model_gate(pcb_file)
        if model_gate.ok:
            return self._pass("PRODUCTION_MODEL", "pcb", "Footprint kimlikleri ve pad-net modeli uretim kapisini gecti.")
        return self._fail(
            "PRODUCTION_MODEL",
            "pcb",
            "blocker",
            model_gate.evidence_summary,
            "Sentetik/genel footprintleri resmi KiCad footprintleriyle degistir ve tum no-net padleri bilincli NC veya net baglantisi olarak modelle.",
        )

    def _check_drc_consistency(
        self,
        layout_status_file: Path,
        pcb_file: Path,
        drc_report_file: Path,
        verification_manifest_file: Path,
    ) -> ReadinessCheck:
        gate_failure = self._layout_gate_failure(layout_status_file, pcb_file, drc_report_file, verification_manifest_file)
        if gate_failure is None:
            return self._pass("DRC_EVIDENCE", "drc", "Board verification manifest aktif PCB ve KiCad DRC raporuyla tutarli; DRC=0.")
        return self._fail(
            "DRC_EVIDENCE",
            "drc",
            "blocker",
            gate_failure,
            "DRC sonucunu aktif board dosyasiyla ayni kosuda yeniden uret.",
        )

    def _layout_gate_failure(
        self,
        layout_status_file: Path,
        pcb_file: Path,
        drc_report_file: Path | None = None,
        verification_manifest_file: Path | None = None,
    ) -> str | None:
        if verification_manifest_file is not None and verification_manifest_file.exists() and drc_report_file is not None:
            return manifest_gate_failure(verification_manifest_file, pcb_file=pcb_file, drc_report_file=drc_report_file)
        if not layout_status_file.exists():
            return "Layout optimizer durum dosyasi yok."
        data = json.loads(layout_status_file.read_text(encoding="utf-8"))
        final_count = int(data.get("final_violation_count", -1))
        manufacturing_ready = bool(data.get("manufacturing_ready", False))
        pcb_text = pcb_file.read_text(encoding="utf-8", errors="ignore") if pcb_file.exists() else ""
        pcb_has_footprints = "pcbnew unavailable" not in pcb_text and "(footprint" in pcb_text
        if final_count == 0 and manufacturing_ready and pcb_has_footprints:
            return None
        return f"DRC status final={final_count}, manufacturing_ready={manufacturing_ready}; aktif PCB kaniti tutarsiz."

    def _check_simulation_evidence(self) -> ReadinessCheck:
        simulation_dir = Path("outputs/simulation")
        evidence = list(simulation_dir.glob("*.json")) + list(simulation_dir.glob("*.raw")) + list(simulation_dir.glob("*.log"))
        if not evidence:
            return self._fail(
                "REAL_SIMULATION",
                "simulation",
                "blocker",
                "SPICE/SI/PI/thermal kosu kaniti bulunamadi.",
                "Ngspice/KiCad sim, guc butcesi, RF impedance ve termal analiz raporlarini uret.",
            )
        report_file = simulation_dir / "simulation_report.json"
        if report_file.exists():
            report = json.loads(report_file.read_text(encoding="utf-8"))
            statuses = [item.get("status") for item in report.get("results", []) if isinstance(item, dict)]
            if any(status == "fail" for status in statuses):
                return self._fail(
                    "REAL_SIMULATION",
                    "simulation",
                    "blocker",
                    "Simulasyon raporu fail sonucu iceriyor.",
                    "Fail olan guc/RF/termal maddeleri duzelt.",
                )
            if any(status == "review" for status in statuses):
                return self._warn(
                    "REAL_SIMULATION",
                    "simulation",
                    "review",
                    f"{len(evidence)} simulasyon kaniti bulundu; bazi maddeler inceleme istiyor.",
                    "Review maddelerini datasheet ve uretici stackup ile dogrula.",
                )
        return self._pass("REAL_SIMULATION", "simulation", f"{len(evidence)} simulasyon kaniti bulundu.")

    def _check_pcba_evidence(
        self,
        fabrication_package_file: Path,
        layout_status_file: Path,
        pcb_file: Path,
        drc_report_file: Path,
        verification_manifest_file: Path,
    ) -> ReadinessCheck:
        gate_failure = self._layout_gate_failure(layout_status_file, pcb_file, drc_report_file, verification_manifest_file)
        if gate_failure is not None:
            return self._fail(
                "PCBA_HANDOFF",
                "pcba",
                "blocker",
                f"PCBA paketi guncel DRC kapisini gecemez: {gate_failure}",
                "DRC=0 ve manufacturing_ready=true olmadan PCBA handoff'u gecirme.",
            )
        if not fabrication_package_file.exists():
            return self._fail("PCBA_HANDOFF", "pcba", "blocker", "fabrication_package.json yok.", "Faz 5 paketleme komutunu calistir.")
        data = json.loads(fabrication_package_file.read_text(encoding="utf-8"))
        categories = {item.get("category") for item in data.get("files", []) if isinstance(item, dict)}
        required = {"gerber", "drill", "pick_and_place", "bom"}
        missing = sorted(required - categories)
        if missing:
            return self._fail(
                "PCBA_HANDOFF",
                "pcba",
                "blocker",
                f"PCBA handoff kategorileri eksik: {', '.join(missing)}.",
                "Gerber, drill, BOM ve CPL paketini yeniden uret.",
            )
        assembly_dir = Path("outputs/assembly")
        drawings = list(assembly_dir.glob("*.pdf")) + list(assembly_dir.glob("*.svg"))
        models = list(assembly_dir.glob("*.glb")) + list(assembly_dir.glob("*.step"))
        if drawings and models:
            return self._pass("PCBA_HANDOFF", "pcba", f"Gerber/drill/BOM/CPL + {len(drawings)} drawing + {len(models)} 3D model kaniti bulundu.")
        return self._warn(
            "PCBA_HANDOFF",
            "pcba",
            "review",
            "Gerber/drill/BOM/CPL var; assembly drawing veya 3D model kaniti eksik.",
            "Assembly drawing, fabrication drawing ve 3D PCBA export ekle.",
        )

    def _check_fabrication_zip(
        self,
        production_zip: Path,
        layout_status_file: Path,
        pcb_file: Path,
        drc_report_file: Path,
        verification_manifest_file: Path,
    ) -> ReadinessCheck:
        gate_failure = self._layout_gate_failure(layout_status_file, pcb_file, drc_report_file, verification_manifest_file)
        if gate_failure is not None:
            return self._fail(
                "FAB_ZIP",
                "export",
                "blocker",
                f"ZIP paketi guncel DRC kapisini gecemez: {gate_failure}",
                "DRC=0 ve manufacturing_ready=true olmadan uretim ZIP'i gecer sayma.",
            )
        if not production_zip.exists():
            return self._fail("FAB_ZIP", "export", "blocker", "Uretim ZIP paketi yok.", "Faz 5 paketleme komutunu calistir.")
        with zipfile.ZipFile(production_zip) as archive:
            names = archive.namelist()
        has_gerber = any(name.startswith("gerber/") for name in names)
        has_drill = any(name.startswith("drill/") for name in names)
        has_position = any(name.startswith("position/") for name in names)
        has_bom = any(name.startswith("bom/") for name in names)
        if has_gerber and has_drill and has_position and has_bom:
            return self._pass("FAB_ZIP", "export", f"ZIP paketi {len(names)} dosya iceriyor.")
        return self._fail("FAB_ZIP", "export", "blocker", "ZIP icinde tum uretim kategorileri yok.", "ZIP paketini yeniden olustur.")

    def _build_report(self, checks: list[ReadinessCheck]) -> EngineeringReadinessReport:
        pass_count = sum(1 for check in checks if check.status == "pass")
        blocker_count = sum(1 for check in checks if check.severity == "blocker" and check.status == "fail")
        review_count = sum(1 for check in checks if check.status == "warn")
        readiness_percent = round((pass_count / len(checks)) * 100)
        overall_status = "blocked" if blocker_count else ("review_required" if review_count else "production_candidate")
        summary = (
            f"Muhendislik denetimi: {overall_status}. "
            f"{pass_count}/{len(checks)} kontrol gecti, {blocker_count} bloklayici sorun, {review_count} inceleme uyarisi."
        )
        return EngineeringReadinessReport(
            schema="ENGINEERING_READINESS_V1",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            overall_status=overall_status,
            readiness_percent=readiness_percent,
            summary=summary,
            checks=checks,
        )

    def _pass(self, check_id: str, domain: str, evidence: str) -> ReadinessCheck:
        return ReadinessCheck(check_id, domain, "pass", "info", evidence, "Islem gerekmiyor.")

    def _warn(self, check_id: str, domain: str, severity: str, evidence: str, required_action: str) -> ReadinessCheck:
        return ReadinessCheck(check_id, domain, "warn", severity, evidence, required_action)

    def _fail(self, check_id: str, domain: str, severity: str, evidence: str, required_action: str) -> ReadinessCheck:
        return ReadinessCheck(check_id, domain, "fail", severity, evidence, required_action)

    def _write_json(self, report: EngineeringReadinessReport, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")


def main() -> int:
    project_dir = Path("outputs/kicad") / DEFAULT_PROJECT
    parser = argparse.ArgumentParser(description="Audit real engineering readiness of OmniCircuit artifacts.")
    parser.add_argument("--schematic-file", default=str(project_dir / f"{DEFAULT_PROJECT}.kicad_sch"))
    parser.add_argument("--erc-report-file", default=str(project_dir / "erc_report.json"))
    parser.add_argument("--pcb-file", default=str(project_dir / f"{DEFAULT_PROJECT}.kicad_pcb"))
    parser.add_argument("--backup-pcb-file", default=str(project_dir / f"{DEFAULT_PROJECT}.before_optimizer.kicad_pcb"))
    parser.add_argument("--bom-file", default="BOM.csv")
    parser.add_argument("--netlist-file", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--layout-status-file", default="outputs/phase4/layout_optimization_status.json")
    parser.add_argument("--drc-report-file", default=str(project_dir / "manufacturing" / "drc_report.json"))
    parser.add_argument("--verification-manifest-file", default="outputs/engineering/board_verification_manifest.json")
    parser.add_argument("--fabrication-package-file", default="outputs/fabrication/fabrication_package.json")
    parser.add_argument("--production-zip", default="outputs/fabrication/Quantum_Mind_Anchor_v2_4_Production.zip")
    parser.add_argument("--output", default="outputs/engineering/engineering_readiness_report.json")
    parser.add_argument("--asset-output", default="assets/generated/engineering_readiness_report.json")
    args = parser.parse_args()
    service = EngineeringReadinessService()
    report = service.audit(
        schematic_file=Path(args.schematic_file),
        erc_report_file=Path(args.erc_report_file),
        pcb_file=Path(args.pcb_file),
        backup_pcb_file=Path(args.backup_pcb_file),
        bom_file=Path(args.bom_file),
        netlist_file=Path(args.netlist_file),
        layout_status_file=Path(args.layout_status_file),
        drc_report_file=Path(args.drc_report_file),
        verification_manifest_file=Path(args.verification_manifest_file),
        fabrication_package_file=Path(args.fabrication_package_file),
        production_zip=Path(args.production_zip),
        output_path=Path(args.output),
        asset_output=Path(args.asset_output) if args.asset_output else None,
    )
    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
