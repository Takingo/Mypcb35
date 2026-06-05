"""AI-assisted error correction: generates Turkish fix proposals for each netlist finding."""
import json
import sys
from pathlib import Path
from typing import Any
from datetime import datetime

# ── UTF-8 PATCH ──
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

from ollama_client import OllamaClient
from input_evidence_validator import InputEvidenceValidator
from ai_repair_service import SAFETY_NET_PATTERNS, ALLOWED_OPS


class AiErrorCorrector:
    """Generates per-finding AI correction proposals with confidence and reasoning."""

    PROPOSALS_SCHEMA = "AI_CORRECTION_PROPOSALS_V1"
    PROPOSAL_SYSTEM_PROMPT = """
Sen OmniCircuit AI'sın — deneyimli bir PCB mühendisi asistanısın.
Sana bir PCB netlist hatası verilecek. Şu beş şeyi JSON olarak döndür:

1. human_readable: Hatanın ne olduğunu Türkçe, açık bir cümleyle anlat (elektronik mühendis için).
2. ai_proposal_text: Yapacağın değişikliği Türkçe soru olarak yaz. Örnek: "R5'in bacağını N_GND'ye bağlayayım mı?"
3. ai_reasoning: Neden bu değişikliği öneriyorsun? Türkçe, 2-4 cümle. Datasheet, BOM veya teknik nedeni açıkla.
4. confidence: Bu öneriden ne kadar eminsin? 0.0-1.0 arası float. 0.85+ çok emin, 0.7-0.85 emin, <0.7 belirsiz.
5. kicad_operation: Uygulanacak KiCad operasyonu (add_net/modify_net/remove_net/add_component/modify_component/remove_component şemalarından biri) veya emin değilsen null.

GÜVENLİK KURALI: AC, MAINS, L, N, ISO, PRIMARY veya E/N sözcükleri içeren netlere ASLA dokunma.
Eğer bu sözcükler varsa: kicad_operation=null, confidence=0.0, ai_reasoning="Güvenlik kritik net, manuel inceleme gerekli."

KURAL: confidence < 0.7 ise ai_uncertain=true olmalı.

Yanıtın tamamen JSON olmalı, başka metin yok:
{
  "human_readable": "...",
  "ai_proposal_text": "...?",
  "ai_reasoning": "...",
  "confidence": 0.85,
  "kicad_operation": { "op": "modify_net", "target": "...", "fields": {...}, "reason": "..." } or null
}
"""

    def __init__(self, project_root: Path | str | None = None):
        if project_root is None:
            project_root = Path.cwd()
        self.root = Path(project_root).resolve()
        self.proposals_path = self.root / "outputs" / "engineering" / "ai_correction_proposals.json"
        self.asset_proposals_path = self.root / "assets" / "generated" / "ai_correction_proposals.json"
        self.netlist_path = self.root / "outputs" / "phase1" / "AI_NETLIST_V1.json"
        self.client = OllamaClient()

    def generate_proposals(self) -> dict[str, Any]:
        """Main entry: collect findings, call AI per finding, write proposals."""
        print("[AiErrorCorrector] Hatalar için AI önerileri oluşturuluyor...")

        # Load netlist
        if not self.netlist_path.exists():
            print(f"[ERROR] Netlist bulunamadı: {self.netlist_path}")
            return {
                "status": "error",
                "message": "Netlist not found",
                "total_proposals": 0,
            }

        netlist = json.loads(self.netlist_path.read_text(encoding="utf-8-sig"))

        # Collect findings from input validator
        validator = InputEvidenceValidator(self.root)
        validator_result = validator.validate()
        findings = validator_result.get("findings", [])

        if not findings:
            print("[AiErrorCorrector] Hata bulunamadı. Boş proposals file yazılıyor.")
            empty_proposals = {
                "schema": self.PROPOSALS_SCHEMA,
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "netlist_file": str(self.netlist_path),
                "provider": self.client.provider,
                "model": self.client.model,
                "proposals": [],
                "summary": {"total": 0, "pending": 0, "auto_applicable": 0, "needs_user": 0, "safety_critical": 0},
            }
            self._write_proposals(empty_proposals)
            return {"status": "no_findings", "total_proposals": 0}

        # Filter only error/warn findings (review findings are user questions, not AI proposals)
        actionable_findings = [f for f in findings if f.get("severity") in ("error", "warn")]

        proposals = []
        for idx, finding in enumerate(actionable_findings, 1):
            print(f"[AiErrorCorrector] {idx}/{len(actionable_findings)} hata için öneri üretiliyor: {finding.get('id', '?')}")
            proposal = self._propose_for_finding(finding, netlist, idx)
            proposals.append(proposal)

        # Build proposals report
        report = {
            "schema": self.PROPOSALS_SCHEMA,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "netlist_file": str(self.netlist_path),
            "provider": self.client.provider,
            "model": self.client.model,
            "proposals": proposals,
            "summary": self._build_summary(proposals),
        }

        self._write_proposals(report)

        print(f"[AiErrorCorrector] Tamamlandı: {len(proposals)} öneri üretildi.")
        return {
            "status": "success",
            "total_proposals": len(proposals),
            "auto_applicable": sum(1 for p in proposals if p["auto_applicable"]),
            "safety_critical": sum(1 for p in proposals if p["is_safety_critical"]),
        }

    def _propose_for_finding(self, finding: dict[str, Any], netlist: dict[str, Any], idx: int = 0) -> dict[str, Any]:
        """Generate a single proposal via AI."""
        finding_id = finding.get("id", "UNKNOWN")
        category = finding.get("category", "")
        severity = finding.get("severity", "")
        description = finding.get("description", "")
        proposal_id = f"PROP_{str(idx).zfill(3)}"

        # Check if safety-critical
        is_safety = self._is_safety_critical(finding, netlist)
        if is_safety:
            return {
                "id": proposal_id,
                "source_finding_id": finding_id,
                "error_category": category,
                "error_severity": severity,
                "human_readable": description,
                "ai_proposal_text": "Bu bağlantı güvenlik kritik (AC/İzolasyon). Manuel mühendis incelemesi zorunludur.",
                "ai_reasoning": "AC, MAINS, L, N, ISO veya PRIMARY neti tespit edildi. AI bu bağlantılara dokunmaz.",
                "confidence": 0.0,
                "is_safety_critical": True,
                "safety_reason": "Safety net pattern detected",
                "ai_uncertain": True,
                "auto_applicable": False,
                "kicad_operation": None,
                "status": "pending",
            }

        # Build focused prompt for this finding
        user_prompt = self._build_proposal_prompt(finding, netlist)

        # Call AI
        try:
            result = self.client.generate_json(
                model=self.client.model,
                system_prompt=self.PROPOSAL_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
        except Exception as e:
            print(f"[ERROR] AI çağrısı başarısız ({finding_id}): {e}")
            return {
                "id": proposal_id,
                "source_finding_id": finding_id,
                "error_category": category,
                "error_severity": severity,
                "human_readable": description,
                "ai_proposal_text": "AI çağrısı başarısız oldu. Manuel inceleme gerekli.",
                "ai_reasoning": f"Hata: {str(e)[:100]}",
                "confidence": 0.0,
                "is_safety_critical": False,
                "ai_uncertain": True,
                "auto_applicable": False,
                "kicad_operation": None,
                "status": "pending",
            }

        # Parse AI response
        human_readable = result.get("human_readable", description)
        ai_proposal_text = result.get("ai_proposal_text", "Önerim yok.")
        ai_reasoning = result.get("ai_reasoning", "")
        confidence = float(result.get("confidence", 0.0))
        ai_uncertain = confidence < 0.7

        # Validate kicad_operation if present
        kicad_op = result.get("kicad_operation")
        if kicad_op:
            # Re-validate through AiRepairService._validate_one logic
            # For now, accept if op is in ALLOWED_OPS
            if kicad_op.get("op") not in ALLOWED_OPS:
                kicad_op = None
                ai_uncertain = True

        auto_applicable = (
            not ai_uncertain
            and kicad_op is not None
            and confidence >= 0.7
            and not is_safety
        )

        return {
            "id": proposal_id,  # reuse the canonical id computed at function entry (was: f"PROP_{len(str(finding_id)).zfill(3)}" — int has no .zfill, also semantically wrong)
            "source_finding_id": finding_id,
            "error_category": category,
            "error_severity": severity,
            "human_readable": human_readable,
            "ai_proposal_text": ai_proposal_text,
            "ai_reasoning": ai_reasoning,
            "confidence": confidence,
            "is_safety_critical": False,
            "safety_reason": None,
            "ai_uncertain": ai_uncertain,
            "auto_applicable": auto_applicable,
            "kicad_operation": kicad_op,
            "status": "pending",
        }

    def _is_safety_critical(self, finding: dict[str, Any], netlist: dict[str, Any]) -> bool:
        """Check if finding touches safety-critical net patterns."""
        # Extract all net names from finding
        nets_in_finding = set()

        if "target_net" in finding:
            nets_in_finding.add(finding["target_net"])
        if "add_pins" in finding:
            for pin in finding.get("add_pins", []):
                # Pin format: "REF.PIN" → extract net from netlist
                if "." in pin:
                    nets_in_finding.update(self._find_nets_for_pin(pin, netlist))

        # Check against SAFETY_NET_PATTERNS
        for net in nets_in_finding:
            for pattern in SAFETY_NET_PATTERNS:
                if pattern.search(net):
                    return True

        return False

    def _find_nets_for_pin(self, pin_str: str, netlist: dict[str, Any]) -> set[str]:
        """Find nets connected to a pin (REF.PIN format)."""
        ref, pin = pin_str.split(".", 1)
        nets = set()
        for net in netlist.get("nets", []):
            for pin_entry in net.get("pins", []):
                if pin_entry.startswith(f"{ref}.{pin}"):
                    nets.add(net["net"])
                    break
        return nets

    def _build_proposal_prompt(self, finding: dict[str, Any], netlist: dict[str, Any]) -> str:
        """Build a focused user prompt for a single finding."""
        finding_id = finding.get("id", "?")
        category = finding.get("category", "?")
        severity = finding.get("severity", "?")
        description = finding.get("description", "?")

        # Extract context from netlist
        components = netlist.get("components", [])
        nets = netlist.get("nets", [])

        context_lines = [
            f"Hata ID: {finding_id}",
            f"Kategori: {category}",
            f"Şiddet: {severity}",
            f"Açıklama: {description}",
            "",
            "Netlist bağlamı:",
        ]

        # Add relevant components and nets
        target_net = finding.get("target_net")
        if target_net:
            # Find net in netlist
            for net_obj in nets:
                if net_obj.get("net") == target_net:
                    context_lines.append(f"Net '{target_net}': {len(net_obj.get('pins', []))} pin bağlı")
                    for pin in net_obj.get("pins", [])[:3]:  # First 3 pins
                        context_lines.append(f"  - {pin}")
                    break

        # Add orphan pins context
        orphan_pins = finding.get("orphan_pins", [])
        if orphan_pins:
            context_lines.append(f"Bağlı değil: {', '.join(orphan_pins)}")

        # Add BOM context if applicable
        if "MPN" in finding_id:
            ref = finding_id.split("_")[1]
            for comp in components:
                if comp.get("ref") == ref:
                    context_lines.append(f"Komponenent {ref}: value={comp.get('value')}, "
                                        f"part_number={comp.get('part_number')}")
                    break

        return "\n".join(context_lines)

    def _build_summary(self, proposals: list[dict[str, Any]]) -> dict[str, int]:
        """Build summary stats."""
        return {
            "total": len(proposals),
            "pending": sum(1 for p in proposals if p["status"] == "pending"),
            "auto_applicable": sum(1 for p in proposals if p["auto_applicable"]),
            "needs_user": sum(1 for p in proposals if p["ai_uncertain"] and not p["is_safety_critical"]),
            "safety_critical": sum(1 for p in proposals if p["is_safety_critical"]),
        }

    def _write_proposals(self, report: dict[str, Any]) -> None:
        """Write proposals to both outputs/engineering and assets/generated."""
        # Write to outputs/engineering (authoritative copy)
        self.proposals_path.parent.mkdir(parents=True, exist_ok=True)
        self.proposals_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[AiErrorCorrector] Yazıldı: {self.proposals_path}")

        # Write to assets/generated (Flutter reads this)
        self.asset_proposals_path.parent.mkdir(parents=True, exist_ok=True)
        self.asset_proposals_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[AiErrorCorrector] Yazıldı: {self.asset_proposals_path}")


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Generate AI error correction proposals.")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    args = parser.parse_args()

    corrector = AiErrorCorrector(args.project_root)
    result = corrector.generate_proposals()

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in ("success", "no_findings") else 1


if __name__ == "__main__":
    sys.exit(main())
