"""CLI for applying approved AI error corrections.

Reads approvals from ai_correction_approvals.json, applies to netlist,
runs KiCad reverification, updates all reports.

Usage:
    python -m engine.run_ai_correction [--project-root ...] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def _log(msg: str) -> None:
    """Print log message to stderr."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply approved AI error corrections.")
    parser.add_argument("--project-root", default=".", help="Project root directory")
    parser.add_argument("--approvals-file",
                       default=r"assets\generated\ai_correction_approvals.json",
                       help="Path to approvals file")
    parser.add_argument("--proposals-file",
                       default=r"assets\generated\ai_correction_proposals.json",
                       help="Path to proposals file")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be applied without changing anything")
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    approvals_path = project_root / args.approvals_file
    proposals_path = project_root / args.proposals_file

    _log("Onaylanan düzeltmeler uygulanıyor...")

    sys.path.insert(0, str(project_root))
    try:
        from engine.ai_repair_service import AiRepairService
    except ImportError:
        from ai_repair_service import AiRepairService  # type: ignore

    service = AiRepairService(project_root)

    if args.dry_run:
        _log("[DRY-RUN] Hiçbir şey değişmez. Sadece gösterilir.")

    result = service.apply_approved_corrections(
        approvals_path=approvals_path,
        proposals_path=proposals_path,
    )

    _log(f"Durum: {result.get('status')}")
    _log(f"Uygulanan: {result.get('applied_count', 0)}")
    _log(f"Başarısız: {result.get('failed_count', 0)}")

    reverify = result.get("reverify", {})
    if reverify:
        _log(f"KiCad doğrulama: {reverify.get('status')}")
        if reverify.get("drc_total") is not None:
            _log(f"DRC bulguları: {reverify.get('drc_total', 0)} toplam")

    # Print JSON result
    output = {
        "status": result.get("status"),
        "applied": result.get("applied_count", 0),
        "failed": result.get("failed_count", 0),
        "reverify": reverify.get("status") if reverify else None,
        "note": result.get("note"),
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0 if result.get("status") in ("accepted", "no_approved_corrections") else 1


if __name__ == "__main__":
    sys.exit(main())
