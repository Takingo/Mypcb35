"""Closed-loop AI repair service for OmniCircuit.

Durustluk ilkesi (real-not-mock):
- AI yalnizca ADAY oneri uretir; deterministik sema/guvenlik gate'i ve KiCad
  DRC/ERC tek otoritedir.
- Hicbir oneri dogrulanip iyilestirme kanitlanmadan canli netlist'e yazilmaz.
- Saglayici/model ASLA sabitlenmez; engine/ai_settings.json'daki AKTIF saglayici
  kullanilir (OllamaClient: ollama/gemini/openai/nvidia/claude).

Bu modul B-kategorisi (muhendislik karari) hatalarini hedefler: yanlis/eksik
komponent, eksik decoupling, BOM/MPN uyumsuzlugu, net mantik hatasi. Saf
geometrik DRC (via_dangling, clearance) deterministik koda birakilir.
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # codebase çift-import desenini izler
    from engine.drc_parser import KiCadDrcParser
    from engine.input_evidence_validator import InputEvidenceValidator
except ImportError:  # pragma: no cover
    from drc_parser import KiCadDrcParser  # type: ignore
    from input_evidence_validator import InputEvidenceValidator  # type: ignore


REPAIR_SCHEMA = "AI_NETLIST_REPAIR_V1"
RUN_SCHEMA = "AI_REPAIR_RUN_V1"

ALLOWED_OPS = {
    "add_component",
    "remove_component",
    "modify_component",
    "add_net",
    "modify_net",
    "remove_net",
}

# Geometrik/deterministik DRC kategorileri — AI'a GONDERILMEZ (kod cozer).
DETERMINISTIC_CATEGORIES = {"clearance", "courtyard", "drill", "silkscreen", "keepout", "other"}
# Tasarim/yargi gerektiren bulgu kategorileri — AI adayligina uygun.
DESIGN_CATEGORIES = {"unrouted"}

# Guvenlik-kritik net desenleri: AI bunlara evidence'siz dokunamaz.
SAFETY_NET_PATTERNS = (
    re.compile(r"\bAC[_-]", re.I),
    re.compile(r"MAINS", re.I),
    re.compile(r"\bL\b|\bN\b", re.I),
    re.compile(r"ISO", re.I),
    re.compile(r"PRIMARY", re.I),
)

DEFAULT_CONFIDENCE_THRESHOLD = 0.6


REPAIR_SYSTEM_PROMPT = """You are OmniCircuit AI, a PCB repair engineer.
You are given the CURRENT netlist (AI_Netlist_v1) and a list of STRUCTURED design findings
(missing nets, suspect components, BOM/MPN mismatches). Propose the MINIMUM set of netlist
edits to resolve the design-level findings.

Return ONLY valid JSON with this exact schema:
{
  "schema": "AI_NETLIST_REPAIR_V1",
  "operations": [
    {
      "op": "add_component | remove_component | modify_component | add_net | modify_net | remove_net",
      "target": "<existing ref/net, or new ref for add_component>",
      "fields": {
        "type": "...", "value": "...", "manufacturer": "...", "part_number": "...",
        "footprint": "...", "reason": "...", "net_class": "...",
        "pins": ["U3.VCCA", "C93.1"], "add_pins": [], "remove_pins": []
      },
      "reason": "Why this edit is needed",
      "confidence": 0.0,
      "requires_user_evidence": false
    }
  ]
}

RULES:
- Do NOT touch geometry, coordinates, vias, or routing — those are handled deterministically.
- Do NOT modify AC mains / isolation / primary-side nets without setting requires_user_evidence=true.
- If you are unsure about a footprint or pinout, set requires_user_evidence=true.
- Every operation MUST include reason and a calibrated confidence in [0,1].
- Prefer the smallest change that fixes a finding. Return an empty operations list if nothing is safe to change.
"""


class AiRepairService:
    def __init__(self, project_root: Path | None = None,
                 confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD):
        self.root = Path(project_root) if project_root else Path.cwd()
        self.confidence_threshold = confidence_threshold
        self.netlist_path = self.root / "outputs" / "phase1" / "AI_NETLIST_V1.json"
        self.kicad_drc_path = (
            self.root / "outputs" / "kicad"
            / "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
            / "manufacturing" / "drc_report.json"
        )
        self.readiness_path = self.root / "outputs" / "engineering" / "engineering_readiness_report.json"
        self.candidate_path = self.root / "outputs" / "phase1" / "AI_NETLIST_V1.candidate.json"
        self.log_path = self.root / "outputs" / "engineering" / "ai_repair_log.json"
        self.asset_log_path = self.root / "assets" / "generated" / "ai_repair_log.json"

    # ── 1. Bulgu toplama + siniflama ────────────────────────────────────
    def collect_findings(self) -> dict[str, Any]:
        design: list[dict[str, Any]] = []
        deterministic: list[dict[str, Any]] = []

        if self.kicad_drc_path.exists():
            report = KiCadDrcParser().parse_file(self.kicad_drc_path)
            for v in report.violations:
                bucket = design if v.category in DESIGN_CATEGORIES else deterministic
                bucket.append({
                    "id": v.id,
                    "category": v.category,
                    "raw_type": v.raw_type,
                    "severity": v.severity,
                    "description": v.description,
                    "components": sorted({loc.component for loc in v.locations if loc.component}),
                    "repair_hint": v.repair_hint,
                })

        gate_fails: list[dict[str, Any]] = []
        if self.readiness_path.exists():
            readiness = json.loads(self.readiness_path.read_text(encoding="utf-8"))
            for check in readiness.get("checks", []):
                if check.get("status") in ("fail", "warn"):
                    gate_fails.append({
                        "id": check.get("id"),
                        "domain": check.get("domain"),
                        "status": check.get("status"),
                        "severity": check.get("severity"),
                        "evidence": check.get("evidence"),
                        "required_action": check.get("required_action"),
                    })

        # Girdi Paneli (BOM/istek/netlist) kanit dogrulamasi — gercek hatalari
        # AI tamir adayligina tasir. error+warn aksiyon, review ise soru olur.
        input_review: list[dict[str, Any]] = []
        try:
            ie = InputEvidenceValidator(self.root).validate()
            for f in ie.get("findings", []):
                item = {
                    "id": f["id"], "category": f["category"], "severity": f["severity"],
                    "description": f["message"], "source": "input_evidence",
                }
                if f["severity"] in ("error", "warn"):
                    design.append(item)        # AI bunlari duzeltmeye calisabilir
                else:
                    input_review.append(item)  # kapsama farki -> kullaniciya soru
        except Exception as exc:  # noqa: BLE001
            input_review.append({"id": "INPUT_VALIDATOR_ERROR", "severity": "warn",
                                 "category": "validator", "description": str(exc)})

        return {
            "design_findings": design,        # AI adayligina uygun (DRC + input error/warn)
            "deterministic_findings": deterministic,  # kod cozer, AI'a gitmez
            "gate_findings": gate_fails,      # readiness fail/warn
            "input_review_findings": input_review,  # kapsama/soru — toplu AI'a gitmez
        }

    # ── 2. Prompt insasi ────────────────────────────────────────────────
    def build_repair_prompt(self, netlist: dict[str, Any], findings: dict[str, Any]) -> str:
        comp_lines = [
            f"  {c.get('ref')}: {c.get('type')} {c.get('value')} "
            f"[{c.get('manufacturer')} {c.get('part_number')}] fp={c.get('footprint')}"
            for c in netlist.get("components", [])
        ]
        net_lines = [
            f"  {n.get('net')} ({n.get('net_class')}): {', '.join(n.get('pins', []))}"
            for n in netlist.get("nets", [])
        ]
        design = findings.get("design_findings", [])
        gate = findings.get("gate_findings", [])
        return (
            f"PROJECT: {netlist.get('project_name')}\n\n"
            f"CURRENT COMPONENTS ({len(comp_lines)}):\n" + "\n".join(comp_lines) + "\n\n"
            f"CURRENT NETS ({len(net_lines)}):\n" + "\n".join(net_lines) + "\n\n"
            f"DESIGN-LEVEL DRC FINDINGS ({len(design)}):\n" + json.dumps(design, indent=2) + "\n\n"
            f"GATE FINDINGS ({len(gate)}):\n" + json.dumps(gate, indent=2) + "\n\n"
            "Propose AI_NETLIST_REPAIR_V1 operations to resolve the DESIGN-LEVEL and GATE findings only. "
            "Ignore geometric/routing issues."
        )

    # ── 3. Aktif saglayicidan oneri al ──────────────────────────────────
    def request_proposals(self, netlist: dict[str, Any], findings: dict[str, Any]) -> dict[str, Any]:
        try:
            from engine.ollama_client import OllamaClient
        except ImportError:  # pragma: no cover
            from ollama_client import OllamaClient  # type: ignore

        client = OllamaClient()  # AKTIF saglayici/model — sabitlenmez
        user_prompt = self.build_repair_prompt(netlist, findings)
        raw = client.generate_json(
            model=client.model,
            system_prompt=REPAIR_SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )
        return {
            "provider": client.provider,
            "model": client.model,
            "operations": raw.get("operations", []) if isinstance(raw, dict) else [],
        }

    # ── 4. Dogrulama gate (sema + guvenlik + confidence) ────────────────
    def validate_proposals(self, netlist: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
        existing_refs = {c.get("ref") for c in netlist.get("components", [])}
        existing_nets = {n.get("net") for n in netlist.get("nets", [])}
        # eklenen yeni komponentleri de gecerli pin hedefi say
        added_refs = {
            op.get("target") for op in operations
            if op.get("op") == "add_component" and op.get("target")
        }
        all_refs = existing_refs | added_refs

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        questions: list[dict[str, Any]] = []

        for op in operations:
            verdict = self._validate_one(op, existing_refs, existing_nets, all_refs)
            record = {"operation": op, "verdict": verdict["status"], "reason": verdict["reason"]}
            if verdict["status"] == "accepted":
                accepted.append(op)
            elif verdict["status"] == "needs_evidence":
                questions.append(record)
            else:
                rejected.append(record)
        return {"accepted": accepted, "rejected": rejected, "questions": questions}

    def _validate_one(self, op: dict[str, Any], existing_refs: set, existing_nets: set,
                      all_refs: set) -> dict[str, str]:
        kind = op.get("op")
        target = op.get("target")
        fields = op.get("fields", {}) or {}
        conf = op.get("confidence", 0)

        if kind not in ALLOWED_OPS:
            return {"status": "rejected", "reason": f"izinsiz op: {kind}"}
        if not target:
            return {"status": "rejected", "reason": "target bos"}
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            return {"status": "rejected", "reason": "confidence sayisal degil"}

        # Guvenlik-kritik net'e dokunma -> evidence sart
        touched = [target] + list(fields.get("pins", []) or []) + list(fields.get("add_pins", []) or [])
        for t in touched:
            if any(p.search(str(t)) for p in SAFETY_NET_PATTERNS):
                if not op.get("requires_user_evidence", False):
                    return {"status": "needs_evidence",
                            "reason": f"guvenlik-kritik hedef ({t}) evidence gerektirir"}
                return {"status": "needs_evidence", "reason": f"guvenlik-kritik hedef ({t})"}

        if op.get("requires_user_evidence", False):
            return {"status": "needs_evidence", "reason": "AI emin degil (requires_user_evidence)"}
        if conf < self.confidence_threshold:
            return {"status": "rejected", "reason": f"dusuk confidence {conf} < {self.confidence_threshold}"}

        # Hedef varlik tutarliligi
        if kind in ("remove_component", "modify_component") and target not in existing_refs:
            return {"status": "rejected", "reason": f"komponent yok: {target}"}
        if kind in ("remove_net", "modify_net") and target not in existing_nets:
            return {"status": "rejected", "reason": f"net yok: {target}"}
        if kind == "add_component" and target in existing_refs:
            return {"status": "rejected", "reason": f"ref zaten var: {target}"}
        if kind == "add_component":
            for key in ("type", "value", "part_number", "footprint"):
                if not fields.get(key):
                    return {"status": "rejected", "reason": f"add_component eksik alan: {key}"}
        # net pinleri gercek komponente isaret etmeli
        for pin in list(fields.get("pins", []) or []) + list(fields.get("add_pins", []) or []):
            ref = str(pin).split(".")[0]
            if ref not in all_refs:
                return {"status": "rejected", "reason": f"pin bilinmeyen komponente isaret ediyor: {pin}"}

        return {"status": "accepted", "reason": "sema+guvenlik+confidence gecti"}

    # ── 4b. Deterministik BOM hizalama (BOM otorite: value+MPN+uretici) ──
    def deterministic_bom_fixes(self, netlist: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Acik durum: netlist komponent metadata'si kullanicinin BOM'undan
        sapmissa (value/part_number/manufacturer), BOM otorite kabul edilip
        deterministik hizalanir. footprint KiCad-dogrulanmis oldugu icin
        DOKUNULMAZ. Belirsiz/yargi gereken durumlar AI'a birakilir.

        Her degisiklik audit icin loglanir; regresyon olursa reverify rollback eder.
        """
        bom = InputEvidenceValidator(self.root).load_bom()
        cand = copy.deepcopy(netlist)
        fixes: list[dict[str, Any]] = []
        for c in cand.get("components", []):
            ref = c.get("ref")
            if ref not in bom:
                continue
            for field in ("value", "part_number", "manufacturer"):
                bom_val = (bom[ref].get(field) or "").strip()
                cur = (c.get(field) or "").strip()
                if bom_val and cur.lower() != bom_val.lower():
                    fixes.append({"ref": ref, "field": field, "from": cur, "to": bom_val,
                                  "source": "bom_authoritative"})
                    c[field] = bom_val
        return cand, fixes

    # ── 5. Candidate'e uygula (canli dosyaya DEGIL) ─────────────────────
    def apply_to_candidate(self, netlist: dict[str, Any], accepted: list[dict[str, Any]]) -> dict[str, Any]:
        cand = copy.deepcopy(netlist)
        comps = cand.setdefault("components", [])
        nets = cand.setdefault("nets", [])
        comp_by_ref = {c.get("ref"): c for c in comps}
        net_by_name = {n.get("net"): n for n in nets}

        for op in accepted:
            kind = op.get("op")
            target = op.get("target")
            f = op.get("fields", {}) or {}
            if kind == "add_component":
                comps.append({
                    "ref": target, "type": f.get("type", ""), "value": f.get("value", ""),
                    "manufacturer": f.get("manufacturer", ""), "part_number": f.get("part_number", ""),
                    "footprint": f.get("footprint", ""), "reason": op.get("reason", "AI repair"),
                    "constraints": f.get("constraints", []),
                })
            elif kind == "remove_component":
                comps[:] = [c for c in comps if c.get("ref") != target]
            elif kind == "modify_component" and target in comp_by_ref:
                for key in ("type", "value", "manufacturer", "part_number", "footprint"):
                    if f.get(key):
                        comp_by_ref[target][key] = f[key]
            elif kind == "add_net":
                if target not in net_by_name:
                    nets.append({"net": target, "pins": f.get("pins", []),
                                 "net_class": f.get("net_class", "signal"),
                                 "reason": op.get("reason", "AI repair")})
            elif kind == "remove_net":
                nets[:] = [n for n in nets if n.get("net") != target]
            elif kind == "modify_net" and target in net_by_name:
                net = net_by_name[target]
                pins = set(net.get("pins", []))
                pins |= set(f.get("add_pins", []) or [])
                pins -= set(f.get("remove_pins", []) or [])
                if f.get("pins"):
                    pins = set(f["pins"])
                net["pins"] = sorted(pins)
        return cand

    # ── 5b. Candidate re-verify: KiCad yeniden uret, sadece iyilesirse kabul ──
    def _manifest_counts(self) -> dict[str, int]:
        p = self.root / "outputs" / "engineering" / "board_verification_manifest.json"
        if not p.exists():
            return {"total": 10**9, "error_count": 10**9, "unconnected": 10**9}
        m = json.loads(p.read_text(encoding="utf-8"))
        return {
            "total": int(m.get("total_findings", 0)),
            "error_count": int(m.get("error_count", 0)),
            "unconnected": int(m.get("unconnected_count", 0)),
        }

    def _input_error_count(self) -> int:
        try:
            rep = InputEvidenceValidator(self.root).validate()
            return int(rep.get("counts", {}).get("error", 0)) + int(rep.get("counts", {}).get("warn", 0))
        except Exception:  # noqa: BLE001
            return 10**9

    def _regenerate_board(self) -> None:
        """Aktif netlist'ten KiCad board'u yeniden uret + DRC + audit (gercek araclar)."""
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", "tool/run_kicad_phase2.ps1", "-Export", "-ContinueOnDrcError"],
            cwd=str(self.root), check=False, timeout=600,
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", "tool/run_engineering_audit.ps1"],
            cwd=str(self.root), check=False, timeout=300,
        )

    def reverify_candidate(self, deterministic_applied: bool = False) -> dict[str, Any]:
        """Candidate netlist'i gercek KiCad ile dogrula; yalnizca regresyon yoksa
        VE (girdi hatalari azaliyorsa VEYA deterministik BOM hizalamasi yapildiysa)
        CANLI netliste yaz, aksi halde rollback."""
        if not self.candidate_path.exists():
            return {"status": "no_candidate"}

        before_board = self._manifest_counts()
        before_input = self._input_error_count()
        backup = self.netlist_path.with_name(self.netlist_path.name + ".bak")
        shutil.copy2(self.netlist_path, backup)
        try:
            shutil.copy2(self.candidate_path, self.netlist_path)
            self._regenerate_board()
            after_board = self._manifest_counts()
            after_input = self._input_error_count()

            no_regression = (
                after_board["error_count"] == 0
                and after_board["unconnected"] == 0
                and after_board["total"] <= before_board["total"]
            )
            input_improved = after_input < before_input
            decision = {
                "before_board": before_board, "after_board": after_board,
                "before_input_errwarn": before_input, "after_input_errwarn": after_input,
                "no_regression": no_regression, "input_improved": input_improved,
                "deterministic_applied": deterministic_applied,
            }
            if no_regression and (input_improved or deterministic_applied):
                backup.unlink(missing_ok=True)
                self.candidate_path.unlink(missing_ok=True)
                decision["status"] = "accepted"
                return decision
            # rollback
            shutil.copy2(backup, self.netlist_path)
            self._regenerate_board()
            backup.unlink(missing_ok=True)
            decision["status"] = "rolled_back"
            decision["reason"] = ("regresyon var" if not no_regression
                                  else "ne girdi hatasi azaldi ne deterministik degisiklik var")
            return decision
        except Exception as exc:  # noqa: BLE001
            if backup.exists():
                shutil.copy2(backup, self.netlist_path)
                backup.unlink(missing_ok=True)
            return {"status": "reverify_error", "error": str(exc)}

    # ── 6. Orkestrasyon (dry-run: oneri + dogrulama + log; uygulama opsiyonel) ──
    def run_once(self, apply_candidate: bool = False) -> dict[str, Any]:
        if not self.netlist_path.exists():
            raise FileNotFoundError(f"Netlist yok: {self.netlist_path}")
        netlist = json.loads(self.netlist_path.read_text(encoding="utf-8"))
        findings = self.collect_findings()

        design_count = len(findings["design_findings"])
        gate_count = len(findings["gate_findings"])

        # Deterministik BOM hizalamasi (acik durum) — AI'dan ONCE.
        working, det_fixes = self.deterministic_bom_fixes(netlist)

        input_review = findings.get("input_review_findings", [])
        result: dict[str, Any] = {
            "schema": RUN_SCHEMA,
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "netlist_file": str(self.netlist_path),
            "findings_summary": {
                "design": design_count,
                "deterministic_skipped": len(findings["deterministic_findings"]),
                "gate": gate_count,
                "input_review": len(input_review),
                "deterministic_bom_fixes": len(det_fixes),
            },
            "deterministic_findings": findings["deterministic_findings"],
            "design_findings": findings["design_findings"],
            "gate_findings": findings["gate_findings"],
            "input_review_findings": input_review,
            "deterministic_bom_fixes": det_fixes,
        }

        if design_count == 0 and gate_count == 0 and not det_fixes:
            result["status"] = "no_design_findings"
            result["note"] = "AI tamir gerektiren tasarim/gate bulgusu yok (geometrik bulgular deterministik koda birakildi)."
            self._write_log(result)
            return result

        # AI onerileri (saglayici hatasinda deterministik fix yine de degerli)
        accepted: list[dict[str, Any]] = []
        if design_count or gate_count:
            try:
                proposals = self.request_proposals(working, findings)
                result["provider"] = proposals["provider"]
                result["model"] = proposals["model"]
                result["proposed_operations"] = proposals["operations"]
                validation = self.validate_proposals(working, proposals["operations"])
                accepted = validation["accepted"]
                result["accepted"] = accepted
                result["rejected"] = validation["rejected"]
                result["questions"] = validation["questions"]
            except Exception as exc:  # noqa: BLE001 — durustce raporla, deterministik fix devam
                result["llm_error"] = str(exc)

        if accepted or det_fixes:
            candidate = self.apply_to_candidate(working, accepted)
            self.candidate_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")
            result["candidate_file"] = str(self.candidate_path)
            result["status"] = "candidate_ready"
            result["note"] = ("Candidate netlist yazildi (deterministik BOM hizalamasi + AI onerileri). "
                              "Kabul icin KiCad re-verify gerekir.")
            if apply_candidate:
                reverify = self.reverify_candidate(deterministic_applied=bool(det_fixes))
                result["reverify"] = reverify
                result["status"] = reverify.get("status", "reverify_error")
                result["note"] = {
                    "accepted": "Candidate KiCad re-verify gecti (regresyon yok); canli netlist guncellendi.",
                    "rolled_back": f"Candidate reddedildi ({reverify.get('reason')}); canli netlist eski haline donduruldu.",
                    "reverify_error": "Re-verify sirasinda hata; canli netlist korundu.",
                    "no_candidate": "Candidate bulunamadi.",
                }.get(reverify.get("status"), "Re-verify tamam.")
        else:
            result["status"] = "no_valid_operations"
            result["note"] = "Gecerli/guvenli oneri yok ve deterministik fix yok; canli netlist degismedi."

        self._write_log(result)
        return result

    # ── Interactive Mode: Generate Proposals File ────────────────────────────────────

    def run_interactive(self) -> dict[str, Any]:
        """Interactive mode: generate per-finding proposals file (no auto-apply).

        Delegates to AiErrorCorrector for proposal generation.
        Proposals written to assets/generated/ai_correction_proposals.json.
        """
        try:
            from engine.ai_error_corrector import AiErrorCorrector
        except ImportError:
            from ai_error_corrector import AiErrorCorrector  # type: ignore

        corrector = AiErrorCorrector(self.root)
        result = corrector.generate_proposals()
        return {
            "status": result.get("status"),
            "total_proposals": result.get("total_proposals", 0),
            "auto_applicable": result.get("auto_applicable", 0),
            "safety_critical": result.get("safety_critical", 0),
            "proposals_file": str(corrector.asset_proposals_path),
        }

    def apply_approved_corrections(
        self,
        approvals_path: Path | None = None,
        proposals_path: Path | None = None,
    ) -> dict[str, Any]:
        """Apply approved corrections from approvals file, re-verify, update reports.

        Flow:
        1. Load proposals from proposals_path
        2. Load approvals from approvals_path
        3. Validate approved operations through _validate_one gate
        4. Apply to candidate netlist
        5. Run KiCad reverify
        6. If successful: write live netlist + update reports
        7. Update proposal statuses in proposals file (applied/failed)

        Args:
            approvals_path: Path to ai_correction_approvals.json
            proposals_path: Path to ai_correction_proposals.json

        Returns:
            dict with status, applied_count, failed_count, reverify info
        """
        if approvals_path is None:
            approvals_path = self.root / "assets" / "generated" / "ai_correction_approvals.json"
        if proposals_path is None:
            proposals_path = self.root / "assets" / "generated" / "ai_correction_proposals.json"

        result: dict[str, Any] = {
            "status": "error",
            "applied_count": 0,
            "failed_count": 0,
            "reverify": None,
        }

        # Load proposals and approvals
        if not proposals_path.exists():
            result["note"] = f"Proposals file not found: {proposals_path}"
            return result

        proposals_data = json.loads(proposals_path.read_text(encoding="utf-8"))
        proposals = {p["id"]: p for p in proposals_data.get("proposals", [])}

        if not approvals_path.exists():
            result["note"] = f"Approvals file not found: {approvals_path}"
            return result

        approvals_data = json.loads(approvals_path.read_text(encoding="utf-8"))
        approved_ids = {
            d["proposal_id"] for d in approvals_data.get("decisions", [])
            if d.get("decision") == "approved"
        }

        if not approved_ids:
            result["status"] = "no_approved_corrections"
            result["note"] = "No approved proposals found."
            return result

        # Load current netlist as working copy
        if not self.netlist_path.exists():
            result["note"] = f"Netlist not found: {self.netlist_path}"
            return result

        working = json.loads(self.netlist_path.read_text(encoding="utf-8-sig"))

        # Extract operations from approved proposals and re-validate
        approved_ops: list[dict[str, Any]] = []
        for prop_id in approved_ids:
            if prop_id not in proposals:
                continue
            prop = proposals[prop_id]
            kicad_op = prop.get("kicad_operation")
            if not kicad_op:
                result["failed_count"] += 1
                prop["status"] = "failed"
                continue

            # Re-validate through gate
            validation = self.validate_proposals(working, [kicad_op])
            if validation["accepted"]:
                approved_ops.extend(validation["accepted"])
            else:
                result["failed_count"] += 1
                prop["status"] = "failed"

        result["applied_count"] = len(approved_ops)

        # Apply to candidate
        if approved_ops:
            candidate = self.apply_to_candidate(working, approved_ops)
            self.candidate_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

            # Re-verify with KiCad
            reverify = self.reverify_candidate(deterministic_applied=False)
            result["reverify"] = reverify
            result["status"] = reverify.get("status", "reverify_error")

            # Update proposal statuses
            for prop in proposals.values():
                if prop["id"] in approved_ids and prop["status"] == "pending":
                    if result["status"] == "accepted":
                        prop["status"] = "applied"
                    else:
                        prop["status"] = "failed"

            # Write updated proposals back
            proposals_data["proposals"] = list(proposals.values())
            proposals_path.write_text(json.dumps(proposals_data, indent=2, ensure_ascii=False), encoding="utf-8")
        else:
            result["status"] = "no_valid_operations"

        return result

    # ── Logging ────────────────────────────────────────────────────────────

    def _write_log(self, result: dict[str, Any]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        try:
            self.asset_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.asset_log_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"[AI-REPAIR] Asset log yazilamadi: {exc}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="OmniCircuit closed-loop AI repair (proposal + validation).")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--confidence", type=float, default=DEFAULT_CONFIDENCE_THRESHOLD)
    parser.add_argument("--apply", action="store_true",
                        help="candidate re-verify gecerse canli netlist'e yaz.")
    parser.add_argument("--interactive", action="store_true",
                        help="Generate per-finding proposals file (no auto-apply).")
    parser.add_argument("--apply-approved", action="store_true",
                        help="Apply approved corrections from approvals file, then re-verify.")
    args = parser.parse_args()

    service = AiRepairService(Path(args.project_root), confidence_threshold=args.confidence)

    if args.interactive:
        result = service.run_interactive()
    elif args.apply_approved:
        result = service.apply_approved_corrections()
    else:
        result = service.run_once(apply_candidate=args.apply)

    print(json.dumps({
        "status": result.get("status"),
        "provider": result.get("provider"),
        "model": result.get("model"),
        "findings_summary": result.get("findings_summary"),
        "accepted": len(result.get("accepted", [])) if "accepted" in result else 0,
        "rejected": len(result.get("rejected", [])) if "rejected" in result else 0,
        "questions": len(result.get("questions", [])) if "questions" in result else 0,
        "log": str(service.log_path),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
