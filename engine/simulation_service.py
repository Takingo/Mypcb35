from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SimulationResult:
    name: str
    domain: str
    status: str
    metrics: dict[str, Any]
    evidence: str
    recommendation: str


@dataclass(frozen=True)
class SimulationReport:
    schema: str
    generated_at: str
    overall_status: str
    results: list[SimulationResult]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SimulationService:
    """Deterministic engineering simulation/check runner.

    This is not a replacement for vendor SPICE models or a full-wave RF solver.
    It creates auditable first-order evidence for power, RF impedance, thermal
    margin, and safety so the app can distinguish real checked assumptions from
    empty UI claims.
    """

    def run(self, *, bom_file: Path, output_dir: Path, asset_output: Path | None,
            netlist_file: Path | None = None,
            signoff_file: Path | None = None) -> SimulationReport:
        output_dir.mkdir(parents=True, exist_ok=True)
        bom_rows = self._read_bom(bom_file)
        netlist = self._read_netlist(netlist_file)
        signoff = self._read_signoff(signoff_file)
        results = [
            self._power_budget(bom_rows),
            self._rf_impedance(),
            self._thermal_estimate(),
            self._decoupling_coverage(netlist),
            self._safety_check(signoff),
        ]
        overall = "pass" if all(result.status == "pass" for result in results) else "review_required"
        report = SimulationReport(
            schema="SIMULATION_REPORT_V1",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            overall_status=overall,
            results=results,
        )
        self._write_json(report.to_dict(), output_dir / "simulation_report.json")
        self._write_markdown(report, output_dir / "simulation_report.md")
        for result in results:
            self._write_json(asdict(result), output_dir / f"{result.name.lower().replace(' ', '_')}.json")
        if asset_output is not None:
            self._write_json(report.to_dict(), asset_output)
        print(f"Simulation report generated: {overall}")
        return report

    def _read_bom(self, bom_file: Path) -> list[dict[str, str]]:
        if not bom_file.exists():
            return []
        with bom_file.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    def _read_netlist(self, netlist_file: Path | None) -> dict[str, Any]:
        if netlist_file is None or not netlist_file.exists():
            return {}
        try:
            return json.loads(netlist_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _read_signoff(self, signoff_file: Path | None) -> dict[str, Any]:
        path = signoff_file or Path("outputs/engineering/manual_signoff.json")
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _decoupling_coverage(self, netlist: dict[str, Any]) -> SimulationResult:
        """Her aktif IC'nin decoupling kondansatoru var mi? GERCEK board
        artefaktindan (.kicad_pcb) sayilir; board yoksa netlist'e duser.
        Decoupling kondansatorleri board uretiminde (_enrich_netlist) eklendigi
        icin dogru artefakt board'dur."""
        pcb_path = Path("outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
                        "/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb")
        ic_count = 0
        decap_count = 0
        source = "board"
        if pcb_path.exists():
            import re as _re
            pcb_text = pcb_path.read_text(encoding="utf-8", errors="ignore")
            refs = _re.findall(r'\(property "Reference" "([A-Za-z]+\d+)"', pcb_text)
            ic_count = sum(1 for r in refs if r.upper().startswith("U"))
            decap_count = sum(1 for r in refs if r.upper().startswith("C"))
        if ic_count == 0:  # board okunamadiysa netlist'e dus
            source = "netlist"
            components = netlist.get("components", []) if isinstance(netlist, dict) else []
            ic_count = sum(1 for c in components if isinstance(c, dict)
                           and str(c.get("ref", "")).upper().startswith("U"))
            decap_count = sum(1 for c in components if isinstance(c, dict)
                              and str(c.get("ref", "")).upper().startswith("C"))

        adequate = ic_count == 0 or decap_count >= ic_count
        status = "pass" if adequate else "review"
        return SimulationResult(
            name="Decoupling Coverage",
            domain="PI",
            status=status,
            metrics={
                "source": source,
                "active_ic_count": ic_count,
                "decoupling_caps": decap_count,
                "ratio_caps_per_ic": round(decap_count / ic_count, 2) if ic_count else None,
            },
            evidence=(f"Ilk-derece decoupling kapsama analizi ({source}): "
                      f"{decap_count} kondansator / {ic_count} aktif IC."),
            recommendation=(
                "Her IC VCC pinine <5mm 100nF decoupling kondansator yerlestir."
                if not adequate
                else "Decoupling kapsama ilk-derece yeterli; yerlesim mesafesi PCB'de dogrulanmali."
            ),
        )

    def _power_budget(self, bom_rows: list[dict[str, str]]) -> SimulationResult:
        relay_count = sum(1 for row in bom_rows if "g5q" in self._row_text(row))
        relay_current_ma = relay_count * 80.0
        esp32_current_ma = 240.0
        dwm_current_ma = 180.0
        logic_current_ma = 80.0
        five_volt_load_ma = relay_current_ma + 420.0
        hlk_capacity_ma = 1000.0
        three_v_three_load_ma = esp32_current_ma + logic_current_ma + 120.0
        tps54331_capacity_ma = 3000.0
        one_v_eight_load_ma = dwm_current_ma + 40.0
        ldo_part = self._find_part(bom_rows, "u8")
        ldo_capacity_ma = self._ldo_capacity_ma(ldo_part)
        ldo_status = "fail" if one_v_eight_load_ma > ldo_capacity_ma else "pass"
        status = "fail" if ldo_status == "fail" else "pass"
        return SimulationResult(
            name="Power Budget",
            domain="PI",
            status=status,
            metrics={
                "relay_count": relay_count,
                "five_volt_load_ma": five_volt_load_ma,
                "hlk_5m05_capacity_ma": hlk_capacity_ma,
                "three_v_three_load_ma": three_v_three_load_ma,
                "tps54331_capacity_ma": tps54331_capacity_ma,
                "one_v_eight_load_ma": one_v_eight_load_ma,
                "ldo_part": ldo_part or "unknown",
                "ldo_capacity_ma": ldo_capacity_ma,
                "ldo_margin_ma": ldo_capacity_ma - one_v_eight_load_ma,
            },
            evidence="First-order current budget from BOM assumptions.",
            recommendation=(
                "1V8 rail current exceeds selected LDO nominal margin; use higher-current low-noise LDO "
                "or verify DWM3000 peak current from datasheet."
                if status == "fail"
                else "Power rails have first-order current margin."
            ),
        )

    def _rf_impedance(self) -> SimulationResult:
        width_mm = 0.35
        height_mm = 0.20
        er = 4.5
        ratio = width_mm / height_mm
        effective_er = (er + 1.0) / 2.0 + (er - 1.0) / 2.0 / math.sqrt(1.0 + 12.0 / ratio)
        if ratio <= 1.0:
            z0 = (60.0 / math.sqrt(effective_er)) * math.log(8.0 / ratio + 0.25 * ratio)
        else:
            z0 = (120.0 * math.pi) / (math.sqrt(effective_er) * (ratio + 1.393 + 0.667 * math.log(ratio + 1.444)))
        status = "pass" if 45.0 <= z0 <= 55.0 else "review"
        return SimulationResult(
            name="RF Microstrip Impedance",
            domain="SI/RF",
            status=status,
            metrics={
                "trace_width_mm": width_mm,
                "dielectric_height_mm": height_mm,
                "er": er,
                "estimated_z0_ohm": round(z0, 2),
                "target_ohm": 50.0,
            },
            evidence="Closed-form Hammerstad-style microstrip estimate for the specified stackup.",
            recommendation="Confirm with manufacturer stackup field solver and keep RF trace via-free on top layer.",
        )

    def _find_part(self, bom_rows: list[dict[str, str]], reference: str) -> str:
        for row in bom_rows:
            if (row.get("Reference") or "").strip().lower() == reference.lower():
                return row.get("Part Number") or ""
        return ""

    def _ldo_capacity_ma(self, part_number: str) -> float:
        normalized = part_number.lower()
        if "tps7a20" in normalized:
            return 300.0
        if "ap2112" in normalized:
            return 600.0
        if "tps780" in normalized:
            return 150.0
        return 150.0

    def _thermal_estimate(self) -> SimulationResult:
        buck_loss_w = 0.45
        ldo_vdrop = 3.3 - 1.8
        ldo_current_a = 0.12
        ldo_loss_w = ldo_vdrop * ldo_current_a
        ambient_c = 40.0
        theta_ja_c_w = 120.0
        ldo_temp_c = ambient_c + ldo_loss_w * theta_ja_c_w
        status = "pass" if ldo_temp_c < 85.0 else "review"
        return SimulationResult(
            name="Thermal Estimate",
            domain="thermal",
            status=status,
            metrics={
                "buck_loss_w": buck_loss_w,
                "ldo_loss_w": round(ldo_loss_w, 3),
                "ambient_c": ambient_c,
                "estimated_ldo_temp_c": round(ldo_temp_c, 1),
            },
            evidence="First-order junction temperature estimate.",
            recommendation="Validate with real load current and copper area once final footprints are bound.",
        )

    # Manuel mühendis incelemesi gerektiren, otomatik DOĞRULANAMAYAN maddeler.
    MANUAL_REVIEW_ITEMS = (
        "datasheet_pinout_verified",          # Gerçek datasheet kontrolü gerekli
        "rf_stackup_dielectric_verified",     # Üretici field solver gerekli
        "ac_creepage_certification_checked",  # IEC 60664 / IEC 62368 sertifikasyon gerekli
        "spice_si_pi_thermal_models_matched", # Gerçek SPICE modelleri gerekli
    )

    def _safety_check(self, signoff: dict[str, Any] | None = None) -> SimulationResult:
        """AC güvenlik + engineering reality kontrolü.

        Otomatik doğrulanamayan 4 madde vardır (datasheet pinout, RF stackup,
        AC sertifikasyon, SPICE). Bunlar ancak GERÇEK bir mühendis
        `outputs/engineering/manual_signoff.json` dosyasıyla açıkça imzalarsa
        'verified' sayılır. Sistem bu imzayı ASLA kendisi uydurmaz.
        - İmza yoksa: status=review (otomasyon temiz, insan onayı bekliyor).
        - Tüm maddeler imzalıysa: status=pass (mühendis sorumluluğu kaydedildi).
        """
        signoff = signoff or {}
        signed = signoff.get("signed_items", {}) if isinstance(signoff, dict) else {}
        engineer = str(signoff.get("engineer", "")).strip()
        signoff_date = str(signoff.get("date", "")).strip()

        pcb_path = Path("outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
                        "/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb")
        pcb_text = pcb_path.read_text(encoding="utf-8", errors="ignore") if pcb_path.exists() else ""
        has_rule_area = "(rule_area" in pcb_text or "keepout" in pcb_text.lower()
        has_edge_cuts = "(layer \"Edge.Cuts\")" in pcb_text
        pcb_exists = pcb_path.exists() and "(footprint" in pcb_text

        item_status = {item: bool(signed.get(item, False)) for item in self.MANUAL_REVIEW_ITEMS}
        all_signed = all(item_status.values())
        valid_signoff = all_signed and bool(engineer) and bool(signoff_date)
        pending = [item for item, ok in item_status.items() if not ok]

        metrics = {
            "required_ac_clearance_mm": 8.0,
            "pcb_rule_area_found": has_rule_area,
            "pcb_edge_cuts_found": has_edge_cuts,
            "pcb_footprints_present": pcb_exists,
            **item_status,
            "manual_signoff_engineer": engineer or None,
            "manual_signoff_date": signoff_date or None,
            "pending_manual_items": pending,
        }

        if not pcb_exists:
            return SimulationResult(
                name="AC Safety Clearance & Engineering Reality",
                domain="safety",
                status="fail",
                metrics=metrics,
                evidence="PCB dosyası bulunamadı veya footprint içermiyor.",
                recommendation="PCB dosyasını yeniden üret; sonra manuel mühendis sign-off gerekir.",
            )

        if valid_signoff:
            return SimulationResult(
                name="AC Safety Clearance & Engineering Reality",
                domain="safety",
                status="pass",
                metrics=metrics,
                evidence=(
                    f"Tüm manuel mühendislik maddeleri {engineer} tarafından {signoff_date} "
                    "tarihinde imzalandı (datasheet pinout, RF stackup, AC sertifikasyon, SPICE). "
                    f"AC rule area: {'VAR' if has_rule_area else 'YOK'}."
                ),
                recommendation=(
                    "Sign-off kaydedildi. Yine de fiziksel üretim öncesi üretici DFM "
                    "ve prototip doğrulaması önerilir."
                ),
            )

        return SimulationResult(
            name="AC Safety Clearance & Engineering Reality",
            domain="safety",
            status="review",   # imza yoksa otomatik pass OLAMAZ
            metrics=metrics,
            evidence=(
                f"Otomasyon temiz (AC rule area: {'VAR' if has_rule_area else 'YOK'}). "
                f"Manuel mühendis imzası bekleyen maddeler: {', '.join(pending)}. "
                "Bu maddeler BU ARAÇ TARAFINDAN OTOMATİK DOĞRULANAMAZ."
            ),
            recommendation=(
                "GEREKLİ MANUEL KONTROLLER (tamamlayınca sign-off ile imzala):\n"
                "1. Her komponentin datasheet pinout'unu KiCad sembolüyle karşılaştır.\n"
                "2. Üretici stackup field solver ile RF microstrip empedansını doğrula.\n"
                "3. IEC 60664-1 / IEC 62368-1 ile 230VAC creepage+clearance doğrula.\n"
                "4. TPS54331DR, TPS7A2018, HLK-5M05 için gerçek SPICE transient simülasyon.\n"
                "5. DWM3000 1.0mm pitch footprint'ini datasheet land pattern ile karşılaştır.\n"
                "Sonra: tool\\run_engineering_signoff.ps1 -Engineer \"Ad Soyad\" -All"
            ),
        )

    def _row_text(self, row: dict[str, str]) -> str:
        return " ".join(str(value).lower() for value in row.values())

    def _write_json(self, payload: dict[str, Any], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _write_markdown(self, report: SimulationReport, path: Path) -> None:
        lines = [
            "# Simulation Report",
            "",
            f"Generated: {report.generated_at}",
            f"Overall status: {report.overall_status}",
            "",
        ]
        for result in report.results:
            lines.extend(
                [
                    f"## {result.name}",
                    "",
                    f"- Domain: {result.domain}",
                    f"- Status: {result.status}",
                    f"- Evidence: {result.evidence}",
                    f"- Recommendation: {result.recommendation}",
                    "- Metrics:",
                ]
            )
            for key, value in result.metrics.items():
                lines.append(f"  - {key}: {value}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic OmniCircuit engineering simulations.")
    parser.add_argument("--bom-file", default="BOM.csv")
    parser.add_argument("--netlist-file", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--signoff-file", default="outputs/engineering/manual_signoff.json")
    parser.add_argument("--output-dir", default="outputs/simulation")
    parser.add_argument("--asset-output", default="assets/generated/simulation_report.json")
    args = parser.parse_args()
    SimulationService().run(
        bom_file=Path(args.bom_file),
        netlist_file=Path(args.netlist_file) if args.netlist_file else None,
        signoff_file=Path(args.signoff_file) if args.signoff_file else None,
        output_dir=Path(args.output_dir),
        asset_output=Path(args.asset_output) if args.asset_output else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
