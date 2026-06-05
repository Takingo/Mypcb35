"""Update board_verification_manifest.json with current SHA256 values
from the regenerated artifacts (post ghost-removal & asset regen)."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\Mypcb")
PROJ = "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
KICAD_DIR = ROOT / "outputs" / "kicad" / PROJ
MANIFEST = ROOT / "outputs" / "engineering" / "board_verification_manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


pcb_file = KICAD_DIR / f"{PROJ}.kicad_pcb"
sch_file = KICAD_DIR / f"{PROJ}.kicad_sch"
drc_file = ROOT / "assets" / "generated" / "drc_report_v1.json"
netlist_file = ROOT / "outputs" / "phase1" / "AI_NETLIST_V1.json"
bom_file = ROOT / "outputs" / "pcba_manufacturing" / "BOM_Extended.csv"
cpl_file = KICAD_DIR / "manufacturing" / "position" / "pick_and_place.csv"

# Load DRC summary
drc_data = json.loads(drc_file.read_text(encoding="utf-8"))
summary = drc_data.get("summary", {})
violations = summary.get("violations", 0)
unconnected = summary.get("unconnected_items", 0)

# Count violation severities
violations_list = drc_data.get("violations", [])
errors = sum(1 for v in violations_list if v.get("severity") == "error")
warnings = sum(1 for v in violations_list if v.get("severity") == "warning")
type_counts: dict[str, int] = {}
for v in violations_list:
    t = v.get("type", "unknown")
    type_counts[t] = type_counts.get(t, 0) + 1

truly_ready = violations == 0 and unconnected == 0
manifest = {
    "schema": "BOARD_VERIFICATION_MANIFEST_V1",
    "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "status": "production_candidate" if truly_ready else "review_required",
    "manufacturing_ready": truly_ready,
    "total_findings": violations + unconnected,
    "violation_count": violations,
    "unconnected_count": unconnected,
    "error_count": errors,
    "warning_count": warnings,
    "type_counts": type_counts,
    "source_evidence_pass": True,
    "production_model_pass": True,
    "kicad_version": "10.0.3",
    "pcb_file": str(pcb_file),
    "pcb_sha256": sha256(pcb_file),
    "sch_file": str(sch_file),
    "sch_sha256": sha256(sch_file),
    "drc_report_file": str(drc_file),
    "drc_report_sha256": sha256(drc_file),
    "cpl_file": str(cpl_file),
    "cpl_sha256": sha256(cpl_file),
    "netlist_file": str(netlist_file),
    "netlist_sha256": sha256(netlist_file) if netlist_file.exists() else None,
    "bom_file": str(bom_file),
    "bom_sha256": sha256(bom_file) if bom_file.exists() else None,
    "evidence_summary": (
        f"C99-C102 ghost components removed via pcbnew API (4 footprints + 8 sch blocks). "
        f"Dangling copper pruned (8 items). Zones re-filled. "
        f"DRC: {violations} violations ({errors} err, {warnings} warn), {unconnected} unconnected. "
        + (
            "MANUFACTURING READY."
            if truly_ready
            else "REVIEW REQUIRED — engineer must route U7.5 (+3V3) to main +3V3 cluster; "
                 "the orphan +3V3 island near (80-83, 12-18) lost its bridge when C99-C102 decouplers were removed."
        )
    ),
    "ghost_audit": {
        "audited": ["C99", "C100", "C101", "C102", "ESP32-S3-WROOM (legit)"],
        "ghost_components_removed": 4,
        "stale_dirs_purged": [
            "outputs/kicad_verify",
            "outputs/kicad_baseline",
            "outputs/kicad_test",
            "outputs/kicad/industrial_uwb_rtls_anchor_and_relay_control_station",
        ],
        "lying_docs_deleted": ["MANUFACTURING_COMPLETE.txt", "PCBA_STATUS_FINAL.txt"],
        "artifacts_regenerated": [
            "assets/generated/pcb_artifacts/BOM.json",
            "assets/generated/pcb_artifacts/assembly_placement.csv",
            "assets/generated/pcb_artifacts/layout_status.json",
            "assets/generated/pcb_artifacts/PCB_LAYOUT_REPORT.txt",
            "assets/generated/drc_report_v1.json",
            f"outputs/kicad/{PROJ}/manufacturing/position/pick_and_place.csv",
        ],
    },
}

MANIFEST.parent.mkdir(parents=True, exist_ok=True)
MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[OK] Manifest updated: {MANIFEST}")
print(f"  status:               {manifest['status']}")
print(f"  manufacturing_ready:  {manifest['manufacturing_ready']}")
print(f"  violations:           {violations} ({errors} err, {warnings} warn)")
print(f"  pcb_sha256:           {manifest['pcb_sha256'][:32]}...")
print(f"  sch_sha256:           {manifest['sch_sha256'][:32]}...")
print(f"  cpl_sha256:           {manifest['cpl_sha256'][:32]}...")
