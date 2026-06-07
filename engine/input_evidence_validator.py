"""Girdi Paneli kanit dogrulayici (Input Evidence Validator).

Kullanicinin verdigi BOM + isterler + netlist arasindaki tutarsizliklari
DETERMINISTIK olarak yakalar. AI'a gitmeden once gercek hatalari listeler:
- net pin'i olmayan komponente isaret ediyor (gercek bug)
- BOM <-> netlist ref kapsama farki (eksik/fazla komponent)
- ayni ref icin BOM MPN != netlist part_number
- kritik komponentte bos manufacturer/MPN/footprint
- tekrar eden ref, eksik guc/GND netleri

Cikti: INPUT_EVIDENCE_V1 (severity'li bulgular) + UI icin missing_questions.
Bu bulgular AI tamir dongusune (ai_repair_service) "design finding" olarak beslenir.

Durustluk: bu modul kendisi DEGISIKLIK YAPMAZ; yalnizca kanit/bulgu uretir.
Saf stdlib (csv, json) — pcbnew gerekmez.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

try:
    from engine.netlist_source_normalizer import normalize_design_source
except ModuleNotFoundError:
    from netlist_source_normalizer import normalize_design_source  # type: ignore

INPUT_EVIDENCE_SCHEMA = "INPUT_EVIDENCE_V1"

# Elektriksel netliste girmesi BEKLENMEYEN ref onekleri (oto-eksik sayma).
NON_NETLIST_PREFIXES = ("TP",)  # test point; header/connector elektriksel sayilir

# Her tasarimda bulunmasi beklenen guc/toprak netleri.
REQUIRED_NETS = ("GND",)


def expand_refs(token: str) -> list[str]:
    """'R10-R13' -> [R10,R11,R12,R13]; 'TVS1-TVS3' -> [...]; 'U1' -> [U1].
    Virgulle, noktalı virgulle veya boslukla ayrilmis karisik girdileri de acar."""
    out: list[str] = []
    normalized = token.replace("–", "-").replace("—", "-")
    for part in re.split(r"[,;\s]+", normalized):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([A-Za-z_]+)(\d+)\s*-\s*([A-Za-z_]*)(\d+)$", part)
        if m:
            pre1, start, pre2, end = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            prefix = pre2 if pre2 else pre1
            if prefix == pre1 and end >= start:
                out.extend(f"{prefix}{i}" for i in range(start, end + 1))
                continue
        out.append(part)
    return out


def is_bom_section_header(ref_token: str) -> bool:
    text = ref_token.strip()
    return text.startswith("==") and text.endswith("==")


class InputEvidenceValidator:
    def __init__(self, project_root: Path | None = None):
        self.root = Path(project_root) if project_root else Path.cwd()
        self.bom_path = self.root / "BOM.csv"
        self.netlist_path = self.root / "outputs" / "phase1" / "AI_NETLIST_V1.json"
        self.report_path = self.root / "outputs" / "engineering" / "input_evidence_report.json"
        self.asset_report_path = self.root / "assets" / "generated" / "input_evidence_report.json"

    def load_bom(self) -> dict[str, dict[str, str]]:
        """ref -> {value, manufacturer, part_number, package, notes} (aralik acilmis)."""
        bom: dict[str, dict[str, str]] = {}
        if not self.bom_path.exists():
            return bom
        with self.bom_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ref_token = (row.get("Reference") or "").strip()
                if not ref_token:
                    continue
                if is_bom_section_header(ref_token):
                    continue
                meta = {
                    "value": (row.get("Value") or "").strip(),
                    "manufacturer": (row.get("Manufacturer") or "").strip(),
                    "part_number": (row.get("Part Number") or "").strip(),
                    "package": (row.get("Package") or "").strip(),
                    "notes": (row.get("Notes") or "").strip(),
                }
                for ref in expand_refs(ref_token):
                    bom[ref] = meta
        return bom

    def validate(self) -> dict[str, Any]:
        findings: list[dict[str, Any]] = []

        def add(fid: str, severity: str, category: str, message: str, **extra):
            findings.append({"id": fid, "severity": severity, "category": category,
                             "message": message, **extra})

        netlist = json.loads(self.netlist_path.read_text(encoding="utf-8")) if self.netlist_path.exists() else {}
        
        # Apply normalization first so we don't report false positives for BOM vs raw AI mismatch
        if netlist:
            netlist = normalize_design_source(netlist, self.bom_path)
            
        components = netlist.get("components", [])
        nets = netlist.get("nets", [])
        net_refs = {c.get("ref") for c in components if c.get("ref")}
        comp_by_ref = {c.get("ref"): c for c in components}
        bom = self.load_bom()
        bom_refs = set(bom.keys())

        # 1) Tekrar eden ref (gercek bug)
        seen: set[str] = set()
        for c in components:
            r = c.get("ref")
            if r in seen:
                add(f"DUP_{r}", "error", "duplicate_ref", f"Netlist'te tekrar eden ref: {r}", ref=r)
            seen.add(r)

        # 2) Net pin'i olmayan komponente isaret ediyor (gercek bug)
        for n in nets:
            for pin in n.get("pins", []):
                ref = str(pin).split(".")[0]
                if ref and ref not in net_refs:
                    add(f"ORPHAN_{n.get('net')}_{ref}", "error", "pin_orphan",
                        f"'{n.get('net')}' neti olmayan komponente isaret ediyor: {pin}",
                        net=n.get("net"), ref=ref, pin=pin)

        # 3) Eksik zorunlu netler
        present_nets = {n.get("net") for n in nets}
        for req in REQUIRED_NETS:
            if req not in present_nets:
                add(f"MISSING_NET_{req}", "error", "missing_net",
                    f"Zorunlu net yok: {req}", net=req)

        # 4) BOM'da olup netliste girmemis komponentler (kapsama)
        for ref in sorted(bom_refs - net_refs):
            if self._covered_by_netlist_alias(ref, net_refs, comp_by_ref):
                continue
            if ref.rstrip("0123456789").upper().startswith(NON_NETLIST_PREFIXES):
                continue  # TP gibi elektriksel olmayanlar
            add(f"BOM_ONLY_{ref}", "review", "bom_not_in_netlist",
                f"BOM'da var, netliste girmemis: {ref} "
                f"({bom[ref].get('value')} / {bom[ref].get('part_number')})",
                ref=ref, bom=bom[ref])

        # 5) Netliste olup BOM'da olmayan komponentler
        for ref in sorted(net_refs - bom_refs):
            c = comp_by_ref.get(ref, {})
            if self._covered_by_bom_alias(ref, bom_refs, c):
                continue
            add(f"NL_ONLY_{ref}", "review", "netlist_not_in_bom",
                f"Netliste var, BOM'da yok: {ref} ({c.get('value')} / {c.get('part_number')})",
                ref=ref)

        # 6) MPN uyumsuzlugu (ayni ref, farkli part_number)
        for ref in sorted(net_refs & bom_refs):
            nl_mpn = (comp_by_ref[ref].get("part_number") or "").strip()
            bom_mpn = (bom[ref].get("part_number") or "").strip()
            if nl_mpn and bom_mpn and nl_mpn.lower() != bom_mpn.lower():
                add(f"MPN_{ref}", "warn", "mpn_mismatch",
                    f"{ref} MPN uyumsuz: netlist='{nl_mpn}' vs BOM='{bom_mpn}'",
                    ref=ref, netlist_mpn=nl_mpn, bom_mpn=bom_mpn)

        # 7) Kritik komponentte bos alan (IC/modul/regulator)
        critical_types = ("mcu", "uwb_module", "regulator", "ldo", "buck", "level_shifter", "module")
        for c in components:
            ctype = (c.get("type") or "").lower()
            is_critical = any(k in ctype for k in critical_types) or (c.get("ref", "").startswith("U"))
            if not is_critical:
                continue
            for field in ("manufacturer", "part_number", "footprint"):
                if not (c.get(field) or "").strip():
                    add(f"EMPTY_{c.get('ref')}_{field}", "warn", "empty_critical_field",
                        f"{c.get('ref')} kritik komponentte bos alan: {field}", ref=c.get("ref"), field=field)

        severity_counts = {s: sum(1 for f in findings if f["severity"] == s)
                           for s in ("error", "warn", "review")}
        # UI sorulacaklar: error + review (kullanici karari gereken) + evidence isteyenler
        questions = [
            {"id": f["id"], "category": f["category"], "ask": f["message"],
             "severity": f["severity"]}
            for f in findings if f["severity"] in ("error", "review")
        ]

        report = {
            "schema": INPUT_EVIDENCE_SCHEMA,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "bom_file": str(self.bom_path),
            "netlist_file": str(self.netlist_path),
            "counts": {
                "components": len(components),
                "nets": len(nets),
                "bom_refs": len(bom_refs),
                "findings": len(findings),
                **severity_counts,
            },
            "status": "fail" if severity_counts["error"] else ("review" if findings else "pass"),
            "findings": findings,
            "missing_questions": questions,
        }
        self._write(report)
        return report

    def _covered_by_netlist_alias(
        self,
        bom_ref: str,
        net_refs: set[str],
        comp_by_ref: dict[str, dict[str, Any]],
    ) -> bool:
        if bom_ref != "J1_AC" or "J1" not in net_refs:
            return False
        return self._is_accepted_ac_connector_alias(comp_by_ref.get("J1", {}))

    def _covered_by_bom_alias(
        self,
        net_ref: str,
        bom_refs: set[str],
        component: dict[str, Any],
    ) -> bool:
        if net_ref != "J1" or "J1_AC" not in bom_refs:
            return False
        return self._is_accepted_ac_connector_alias(component)

    def _is_accepted_ac_connector_alias(self, component: dict[str, Any]) -> bool:
        part = str(component.get("part_number", "")).strip()
        text = " ".join(
            str(component.get(key, "")) for key in ("value", "type", "reason", "notes")
        ).lower()
        return part == "1803578" and ("ac" in text or "mains" in text)

    def _write(self, report: dict[str, Any]) -> None:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            self.asset_report_path.parent.mkdir(parents=True, exist_ok=True)
            self.asset_report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"[INPUT-EVIDENCE] Asset yazilamadi: {exc}", flush=True)


# ──────────────────────────────────────────────────────────────────────────────
# Absolute Constraints Guard (Post-step invariant checker)
# ──────────────────────────────────────────────────────────────────────────────
class ConstraintViolation(Exception):
    """Raised when an absolute constraint is violated after a pipeline step."""
    def __init__(self, check_name: str, message: str, details: dict[str, Any] | None = None):
        self.check_name = check_name
        self.details = details or {}
        super().__init__(f"[{check_name}] {message}")


# Critical components that must NEVER be removed from the board
CRITICAL_COMPONENTS = {
    "U15": "W5500 (Ethernet Controller)",
    "J18": "RJ45 (Ethernet Connector)",
    "U2": "DWM3000 (UWB Transceiver)",
    "SK1": "ESP32 Socket Left",
    "SK2": "ESP32 Socket Right",
}

# RF keepout radius around DWM3000 (mm)
RF_KEEPOUT_RADIUS_MM = 5.0

# AC-DC isolation gap (mm)
ISOLATION_GAP_MM = 8.0


class AbsoluteConstraintGuard:
    """Post-step invariant checker for absolute design constraints.

    Call `validate_post_step()` after each pipeline step. If any
    constraint is violated, a `ConstraintViolation` is raised which
    the orchestrator should catch and handle (rollback + retry).
    """

    def __init__(self, project_root: Path | None = None):
        self.root = Path(project_root) if project_root else Path.cwd()
        self.config_path = self.root / "project_config.json"

    def validate_post_step(
        self,
        pcb_path: Path,
        step_name: str,
        *,
        expected_board_size_mm: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Run all absolute constraint checks. Returns list of violations found.
        Raises ConstraintViolation on critical violations."""
        if not pcb_path.exists():
            return []

        violations: list[dict[str, Any]] = []
        pcb_text = pcb_path.read_text(encoding="utf-8", errors="ignore")

        # 1. Board dimensions check
        dim_viols = self._check_board_dimensions(
            pcb_text,
            expected_board_size_mm=expected_board_size_mm,
        )
        violations.extend(dim_viols)

        # 2. Critical components check
        comp_viols = self._check_critical_components(pcb_text)
        violations.extend(comp_viols)

        # 3. Isolation slot check
        iso_viols = self._check_isolation_slot(pcb_text)
        violations.extend(iso_viols)

        # 4. RF keepout check
        rf_viols = self._check_rf_keepout(pcb_text)
        violations.extend(rf_viols)

        # Report
        if violations:
            critical = [v for v in violations if v.get("severity") == "error"]
            if critical:
                raise ConstraintViolation(
                    check_name=f"post_{step_name}",
                    message=f"{len(critical)} absolute constraint(s) violated: "
                            + "; ".join(v["message"] for v in critical[:3]),
                    details={"violations": violations, "step": step_name},
                )
        return violations

    def _check_board_dimensions(
        self,
        pcb_text: str,
        *,
        expected_board_size_mm: tuple[float, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Verify Edge_Cuts match project_config.json board_size_mm."""
        violations: list[dict[str, Any]] = []
        if expected_board_size_mm is not None:
            expected_w, expected_h = expected_board_size_mm
        else:
            if not self.config_path.exists():
                return violations
            try:
                cfg = json.loads(self.config_path.read_text(encoding="utf-8"))
                expected = cfg.get("board_size_mm")
                if not expected or not isinstance(expected, (list, tuple)) or len(expected) < 2:
                    return violations
                expected_w, expected_h = float(expected[0]), float(expected[1])
            except Exception:
                return violations

        # Parse Edge_Cuts from PCB text
        edge_matches = self._edge_line_matches(pcb_text)
        if not edge_matches:
            return violations

        xs, ys = [], []
        for x1, y1, x2, y2 in edge_matches:
            xs.extend([float(x1), float(x2)])
            ys.extend([float(y1), float(y2)])

        actual_w = round(max(xs) - min(xs), 1)
        actual_h = round(max(ys) - min(ys), 1)
        # Allow ±1mm tolerance (auto-routing may adjust edges slightly)
        tolerance = 1.0
        if abs(actual_w - expected_w) > tolerance or abs(actual_h - expected_h) > tolerance:
            violations.append({
                "check": "board_dimensions",
                "severity": "error",
                "message": (
                    f"Board boyutu beklenenden farklı: "
                    f"beklenen {expected_w}x{expected_h}mm, "
                    f"bulunan {actual_w}x{actual_h}mm"
                ),
                "expected": [expected_w, expected_h],
                "actual": [actual_w, actual_h],
            })
        return violations

    def _edge_line_matches(self, pcb_text: str) -> list[tuple[str, str, str, str]]:
        matches: list[tuple[str, str, str, str]] = []
        for block in re.findall(r"\(gr_line\b.*?\n\t\)", pcb_text, flags=re.DOTALL):
            if "Edge.Cuts" not in block and "Edge_Cuts" not in block:
                continue
            start = re.search(r"\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
            end = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
            if start and end:
                matches.append((start.group(1), start.group(2), end.group(1), end.group(2)))
        return matches

    def _check_critical_components(self, pcb_text: str) -> list[dict[str, Any]]:
        """Verify critical components exist in the PCB file."""
        violations: list[dict[str, Any]] = []
        for ref, description in CRITICAL_COMPONENTS.items():
            patterns = (
                rf'\(fp_text\s+reference\s+"?{re.escape(ref)}"?',
                rf'\(property\s+"Reference"\s+"?{re.escape(ref)}"?',
            )
            if not any(re.search(pattern, pcb_text) for pattern in patterns):
                violations.append({
                    "check": "critical_component",
                    "severity": "error",
                    "message": f"Kritik bileşen PCB'de bulunamadı: {ref} ({description})",
                    "ref": ref,
                    "description": description,
                })
        return violations

    def _check_isolation_slot(self, pcb_text: str) -> list[dict[str, Any]]:
        """Check that AC and DC zones have adequate separation.
        Looks for the HLK-10M05 (AC-DC module) and verifies there's
        sufficient clearance around it."""
        violations: list[dict[str, Any]] = []
        hlk_block = self._footprint_block_by_terms(pcb_text, ("HLK", "ACDC", "AC_DC"))
        if not hlk_block:
            return violations  # No AC module found, skip check

        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", hlk_block)
        if not at:
            return violations
        ac_x, ac_y = float(at.group(1)), float(at.group(2))

        # Find all other component positions and check minimum distance
        comp_positions: list[tuple[float, float]] = []
        for block in self._footprint_blocks(pcb_text):
            block_at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", block)
            if block_at:
                comp_positions.append((float(block_at.group(1)), float(block_at.group(2))))
        too_close = []
        for px, py in comp_positions:
            dist = ((px - ac_x) ** 2 + (py - ac_y) ** 2) ** 0.5
            if 0.1 < dist < ISOLATION_GAP_MM:  # Skip self (dist ~0)
                too_close.append((px, py, round(dist, 1)))

        if too_close:
            violations.append({
                "check": "isolation_slot",
                "severity": "error",
                "message": (
                    f"AC-DC izolasyon boşluğu ({ISOLATION_GAP_MM}mm) ihlali: "
                    f"{len(too_close)} bileşen AC modülüne çok yakın"
                ),
                "ac_position": [ac_x, ac_y],
                "too_close_count": len(too_close),
            })
        return violations

    def _check_rf_keepout(self, pcb_text: str) -> list[dict[str, Any]]:
        """Check that no foreign vias/tracks exist within RF_KEEPOUT_RADIUS_MM
        of DWM3000."""
        violations: list[dict[str, Any]] = []
        dwm_block = self._footprint_block_by_reference(pcb_text, "U2")
        if not dwm_block:
            dwm_block = self._footprint_block_by_terms(pcb_text, ("DWM3000",))
        if not dwm_block:
            return violations  # DWM3000 not placed yet

        at = re.search(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)", dwm_block)
        if not at:
            return violations
        dwm_x, dwm_y = float(at.group(1)), float(at.group(2))

        # Check vias near DWM3000
        via_positions = re.findall(
            r'\(via\b[^)]*\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\)',
            pcb_text,
        )
        intruding_vias = 0
        for vx, vy in via_positions:
            dist = ((float(vx) - dwm_x) ** 2 + (float(vy) - dwm_y) ** 2) ** 0.5
            if dist < RF_KEEPOUT_RADIUS_MM:
                intruding_vias += 1

        if intruding_vias > 0:
            violations.append({
                "check": "rf_keepout",
                "severity": "error",
                "message": (
                    f"DWM3000 RF keepout ihlali: {intruding_vias} via "
                    f"{RF_KEEPOUT_RADIUS_MM}mm keepout alanı içinde"
                ),
                "dwm_position": [dwm_x, dwm_y],
                "intruding_vias": intruding_vias,
                "keepout_radius_mm": RF_KEEPOUT_RADIUS_MM,
            })
        return violations

    def _footprint_block_by_reference(self, pcb_text: str, ref: str) -> str:
        for block in self._footprint_blocks(pcb_text):
            if (
                re.search(rf'\(fp_text\s+reference\s+"?{re.escape(ref)}"?', block)
                or re.search(rf'\(property\s+"Reference"\s+"?{re.escape(ref)}"?', block)
            ):
                return block
        return ""

    def _footprint_block_by_terms(self, pcb_text: str, terms: tuple[str, ...]) -> str:
        upper_terms = tuple(term.upper() for term in terms)
        for block in self._footprint_blocks(pcb_text):
            upper = block.upper()
            if any(term in upper for term in upper_terms):
                return block
        return ""

    def _footprint_blocks(self, pcb_text: str) -> list[str]:
        blocks: list[str] = []
        marker = "(footprint "
        pos = 0
        while True:
            start = pcb_text.find(marker, pos)
            if start < 0:
                return blocks
            depth = 0
            end = start
            in_string = False
            escaped = False
            for index in range(start, len(pcb_text)):
                ch = pcb_text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end <= start:
                return blocks
            blocks.append(pcb_text[start:end])
            pos = end


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniCircuit input evidence validator.")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check-constraints", action="store_true",
                        help="Also run absolute constraint checks on existing PCB")
    args = parser.parse_args()
    root = Path(args.project_root)
    report = InputEvidenceValidator(root).validate()
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "counts": report["counts"],
    }, indent=2, ensure_ascii=False))

    if args.check_constraints:
        # Find PCB file and run constraint checks
        try:
            with open(root / "project_config.json", "r", encoding="utf-8") as f:
                cfg = json.load(f)
            proj = cfg.get("project_name", "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs")
            pcb_file = root / "outputs" / "kicad" / proj / f"{proj}.kicad_pcb"
            if pcb_file.exists():
                guard = AbsoluteConstraintGuard(root)
                try:
                    viols = guard.validate_post_step(pcb_file, "cli_check")
                    if viols:
                        print(f"\n[WARN] {len(viols)} constraint warning(s):")
                        for v in viols:
                            print(f"  [{v['severity']}] {v['message']}")
                except ConstraintViolation as e:
                    print(f"\n[CRITICAL] {e}")
                    return 2
        except Exception as exc:
            print(f"Constraint check skipped: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
