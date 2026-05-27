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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

INPUT_EVIDENCE_SCHEMA = "INPUT_EVIDENCE_V1"

# Elektriksel netliste girmesi BEKLENMEYEN ref onekleri (oto-eksik sayma).
NON_NETLIST_PREFIXES = ("TP",)  # test point; header/connector elektriksel sayilir

# Her tasarimda bulunmasi beklenen guc/toprak netleri.
REQUIRED_NETS = ("GND",)


def expand_refs(token: str) -> list[str]:
    """'R10-R13' -> [R10,R11,R12,R13]; 'TVS1-TVS3' -> [...]; 'U1' -> [U1].
    Virgulle ayrilmis ve aralik karisik girdileri de acar."""
    out: list[str] = []
    for part in re.split(r"[,;]", token):
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
            if ref.rstrip("0123456789").upper().startswith(NON_NETLIST_PREFIXES):
                continue  # TP gibi elektriksel olmayanlar
            add(f"BOM_ONLY_{ref}", "review", "bom_not_in_netlist",
                f"BOM'da var, netliste girmemis: {ref} "
                f"({bom[ref].get('value')} / {bom[ref].get('part_number')})",
                ref=ref, bom=bom[ref])

        # 5) Netliste olup BOM'da olmayan komponentler
        for ref in sorted(net_refs - bom_refs):
            c = comp_by_ref.get(ref, {})
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

    def _write(self, report: dict[str, Any]) -> None:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            self.asset_report_path.parent.mkdir(parents=True, exist_ok=True)
            self.asset_report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"[INPUT-EVIDENCE] Asset yazilamadi: {exc}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniCircuit input evidence validator.")
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    report = InputEvidenceValidator(Path(args.project_root)).validate()
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "counts": report["counts"],
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
