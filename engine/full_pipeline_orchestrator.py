"""End-to-end unified pipeline orchestrator.

Replaces the 7-button EDA pipeline panel with a single autonomous run:
takes the 3 user inputs (request / BOM / technical notes), runs every phase
in sequence, auto-repairs recoverable errors, and emits a HITL blocker only
when human judgment is genuinely required.

Output contract — writes ``assets/generated/pipeline_progress.json`` after
every phase transition so the Flutter UI can poll for live progress::

    {
      "schema": "PIPELINE_PROGRESS_V1",
      "status": "running" | "completed" | "awaiting_human" | "failed",
      "current_phase": "drc_cleanup" | null,
      "phases": [
        {"name": "ai_synthesis", "status": "success", "duration_s": 38.6,
         "repair_attempts": 0, "notes": "..."},
        ...
      ],
      "final_artifact": "outputs/fabrication/...zip" | null,
      "hitl_blocker": null | {"session_id": "...", "blocker_type": "...",
                              "question": "...", ...},
      "started_at": "<iso8601>",
      "updated_at": "<iso8601>"
    }

CLI::

    python engine/full_pipeline_orchestrator.py \\
        --request "ESP32-S3 anchor, 2 relays, 220V AC" \\
        --bom-file BOM.csv \\
        --notes "RF 50ohm, 4-layer"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Windows: subprocess pipe ile cagrildiginda sys.stdout.encoding None olabilir
# veya stdout kapali bir handle olabilir. reconfigure'i guvenle uygula.
def _safe_reconfigure_stream(stream: Any) -> None:
    if not hasattr(stream, "reconfigure"):
        return
    try:
        enc = getattr(stream, "encoding", None) or ""
        if enc.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_safe_reconfigure_stream(sys.stdout)
_safe_reconfigure_stream(sys.stderr)

# OSError 22 (subprocess pipe kapatildi) gibi I/O hatalarini yutarak
# pipeline'in son asamada cokmesine engel ol.
_real_print = print

def safe_print(*args: Any, **kwargs: Any) -> None:
    try:
        _real_print(*args, **kwargs)
    except (OSError, UnicodeEncodeError):
        try:
            text = " ".join(str(a) for a in args)
            sys.__stdout__.buffer.write((text + "\n").encode("utf-8", errors="replace"))
            sys.__stdout__.buffer.flush()
        except Exception:
            pass

print = safe_print  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent.parent

try:
    with open(ROOT / "project_config.json", "r", encoding="utf-8") as f:
        _config = json.load(f)
except Exception:
    _config = {}

KCLI = _config.get("kicad_cli_path", r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")
KPY = _config.get("kicad_python_path", r"C:\Program Files\KiCad\10.0\bin\python.exe")
PROGRESS_FILE = ROOT / "assets" / "generated" / "pipeline_progress.json"
PROJ = _config.get("project_name", "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs")

OUTPUT_ROOT = ROOT / _config.get("output_root", "outputs").strip("./\\")
PCB_PATH = OUTPUT_ROOT / "kicad" / PROJ / f"{PROJ}.kicad_pcb"
DRC_PATH = OUTPUT_ROOT / "kicad" / PROJ / "manufacturing" / "drc_report.json"
NETLIST_PATH = OUTPUT_ROOT / "phase1" / "AI_NETLIST_V1.json"
FAB_ZIP_PATH = OUTPUT_ROOT / "fabrication" / f"{PROJ}_Production.zip"

MAX_REPAIR_ATTEMPTS = 3

# ── Autonomous routing correction constants ──────────────────────────────────
VIA_DRILL_DEFAULT = 0.3
VIA_ANNULAR_DEFAULT = 0.6
VIA_DRILL_SMALL = 0.25
VIA_ANNULAR_SMALL = 0.5
BOARD_RESIZE_STEP1 = 1.10  # +10%
BOARD_RESIZE_STEP2 = 1.20  # +20% (from original)
MAX_ROUTING_LOOP_ATTEMPTS = 5

# Passive component prefixes eligible for back-layer migration
BACK_LAYER_ELIGIBLE_PREFIXES = ("R", "C")
BACK_LAYER_MAX_PACKAGE = "0805"  # Only 0402, 0603, 0805 SMD

LAST_CONSTRAINT_VIOLATION: dict[str, Any] | None = None

PHASE_PROGRESS_WEIGHTS = {
    "ai_synthesis": 10,
    "design_feasibility": 10,
    "component_resolution": 10,
    "kicad_generation": 22,
    "drc_cleanup": 14,
    "drc_verify": 14,
    "manifest_sign": 10,
    "fab_package": 10,
}

PHASE_STATUS_MESSAGES = {
    "ai_synthesis": "AI netlist hazırlanıyor",
    "design_feasibility": "Fiziksel uygunluk ve yoğunluk kontrol ediliyor",
    "component_resolution": "Footprint ve pin yapısı doğrulanıyor",
    "kicad_generation": "KiCad proje/PCB dosyaları hazırlanıyor",
    "drc_cleanup": "Routing, temizlik ve zone fill çalışıyor",
    "drc_verify": "DRC ve bağlantı hataları kontrol ediliyor",
    "manifest_sign": "Kanıt manifesti imzalanıyor",
    "fab_package": "Üretim paketi hazırlanıyor",
}


def _iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _current_artifacts() -> tuple[Path, Path, Path]:
    """Return active PCB, DRC report, and manufacturing directory.

    The current fixed-board project is the primary source of truth for this
    pipeline run. Older manifests may still point at previous experiments; do
    not let those stale artifacts become the active production target.
    """
    if PCB_PATH.exists() and DRC_PATH.exists():
        return PCB_PATH, DRC_PATH, DRC_PATH.parent

    manifest_candidates = [
        ROOT / "assets" / "generated" / "board_verification_manifest.json",
        ROOT / "outputs" / "engineering" / "board_verification_manifest.json",
    ]
    for manifest in manifest_candidates:
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            pcb = Path(str(data.get("pcb_file", "")))
            drc = Path(str(data.get("drc_report_file", "")))
            if pcb.exists() and drc.exists():
                return pcb, drc, drc.parent
        except Exception:
            pass

    reports = sorted(
        (ROOT / "outputs" / "kicad").glob("*/manufacturing/drc_report.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if reports:
        drc = reports[0]
        pcbs = sorted(drc.parent.parent.glob("*.kicad_pcb"), key=lambda path: path.stat().st_mtime, reverse=True)
        if pcbs:
            return pcbs[0], drc, drc.parent
    return PCB_PATH, DRC_PATH, DRC_PATH.parent


# ──────────────────────────────────────────────────────────────────────────────
# Autonomous routing correction helpers
# ──────────────────────────────────────────────────────────────────────────────
def _parse_drc_metrics(drc_file: Path) -> dict[str, int]:
    """Extract key DRC counters from a KiCad JSON DRC report."""
    if not drc_file.exists():
        return {"violations": 0, "unconnected": 0, "critical": 0}
    try:
        rep = json.loads(drc_file.read_text(encoding="utf-8"))
    except Exception:
        return {"violations": 0, "unconnected": 0, "critical": 0}
    viols = rep.get("violations", [])
    unconn = rep.get("unconnected_items", [])
    assembly_types = {
        "courtyards_overlap", "silk_overlap", "silk_edge_clearance",
        "silk_over_copper", "pth_inside_courtyard",
    }
    critical = [v for v in viols if v.get("type") not in assembly_types
                and v.get("severity") != "warning"]
    return {
        "violations": len(viols),
        "unconnected": len(unconn),
        "critical": len(critical),
    }


def _iter_sexpr_blocks(text: str, marker: str) -> list[tuple[int, int, str]]:
    blocks: list[tuple[int, int, str]] = []
    pos = 0
    while True:
        start = text.find(marker, pos)
        if start < 0:
            return blocks
        depth = 0
        end = start
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
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
        blocks.append((start, end, text[start:end]))
        pos = end


def _rewrite_sexpr_blocks(
    text: str,
    marker: str,
    rewrite: Callable[[str], str],
) -> tuple[str, int]:
    parts: list[str] = []
    pos = 0
    changed = 0
    for start, end, block in _iter_sexpr_blocks(text, marker):
        parts.append(text[pos:start])
        updated = rewrite(block)
        if updated != block:
            changed += 1
        parts.append(updated)
        pos = end
    parts.append(text[pos:])
    return "".join(parts), changed


def _extract_edge_bbox(pcb_text: str) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for _start, _end, block in _iter_sexpr_blocks(pcb_text, "(gr_line"):
        if "Edge.Cuts" not in block and "Edge_Cuts" not in block:
            continue
        start = re.search(r"\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
        end = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
        if not start or not end:
            continue
        xs.extend([float(start.group(1)), float(end.group(1))])
        ys.extend([float(start.group(2)), float(end.group(2))])
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _current_board_size_from_pcb(pcb_path: Path) -> tuple[float, float] | None:
    if not pcb_path.exists():
        return None
    bbox = _extract_edge_bbox(pcb_path.read_text(encoding="utf-8", errors="ignore"))
    if bbox is None:
        return None
    min_x, min_y, max_x, max_y = bbox
    return round(max_x - min_x, 1), round(max_y - min_y, 1)


def _snapshot_pcb(pcb_path: Path, label: str) -> Path | None:
    if not pcb_path.exists():
        return None
    stamp = int(time.time() * 1_000_000)
    backup = pcb_path.parent / f"{pcb_path.stem}.{label}.{stamp}.bak"
    shutil.copy2(pcb_path, backup)
    return backup


def _restore_pcb(snapshot: Path | None, pcb_path: Path) -> None:
    if snapshot and snapshot.exists():
        shutil.copy2(snapshot, pcb_path)


def _validate_absolute_constraints(
    state: PipelineState,
    step_name: str,
    *,
    expected_board_size_mm: tuple[float, float] | None = None,
) -> bool:
    global LAST_CONSTRAINT_VIOLATION
    pcb_file, _drc_file, _mfg = _current_artifacts()
    if not pcb_file.exists():
        return True
    try:
        sys.path.insert(0, str(ROOT))
        from engine.input_evidence_validator import AbsoluteConstraintGuard

        warnings = AbsoluteConstraintGuard(ROOT).validate_post_step(
            pcb_file,
            step_name,
            expected_board_size_mm=expected_board_size_mm,
        )
        if warnings:
            state.update_notes(
                f"absolute-constraints warnings={len(warnings)} after {step_name}"
            )
        LAST_CONSTRAINT_VIOLATION = None
        return True
    except Exception as exc:  # noqa: BLE001
        details = getattr(exc, "details", {})
        LAST_CONSTRAINT_VIOLATION = {
            "step": step_name,
            "message": str(exc),
            "details": details,
        }
        state.update_notes(f"absolute-constraints failed after {step_name}: {exc}")
        return False


def _shrink_vias(pcb_path: Path, drill: float = VIA_DRILL_SMALL,
                 annular: float = VIA_ANNULAR_SMALL) -> bool:
    """Reduce via sizes in the .kicad_pcb file to improve routing density."""
    if not pcb_path.exists():
        return False
    try:
        text = pcb_path.read_text(encoding="utf-8")

        def rewrite(block: str) -> str:
            size_match = re.search(r"\(size\s+([\d.]+)\)", block)
            drill_match = re.search(r"\(drill\s+([\d.]+)\)", block)
            if not size_match or not drill_match:
                return block
            if float(size_match.group(1)) <= annular and float(drill_match.group(1)) <= drill:
                return block
            block = re.sub(r"\(size\s+[\d.]+\)", f"(size {annular})", block, count=1)
            block = re.sub(r"\(drill\s+[\d.]+\)", f"(drill {drill})", block, count=1)
            return block

        text, changed = _rewrite_sexpr_blocks(text, "(via", rewrite)
        if changed:
            pcb_path.write_text(text, encoding="utf-8")
            return True
    except Exception:
        pass
    return False


def _move_passives_to_back(pcb_path: Path) -> int:
    """Move small SMD passives (R, C in 0402-0805) to B_Cu layer.
    Returns the count of components moved."""
    if not pcb_path.exists():
        return 0
    try:
        text = pcb_path.read_text(encoding="utf-8")
        eligible_packages = ("0402", "0603", "0805")

        def _flip_footprint(block: str) -> str:
            # Check if it's a passive with eligible package
            ref_m = re.search(
                r'\(property\s+"Reference"\s+"?([A-Z]+)\d+"?',
                block,
            ) or re.search(r'\(fp_text\s+reference\s+"?([A-Z]+)\d+"?', block)
            if not ref_m:
                return block
            prefix = ref_m.group(1)
            if prefix not in BACK_LAYER_ELIGIBLE_PREFIXES:
                return block
            # Check package size
            has_eligible_pkg = any(pkg in block for pkg in eligible_packages)
            if not has_eligible_pkg:
                return block
            # Already on back?
            if '(layer "B_Cu")' in block or "(layer B.Cu)" in block:
                return block
            # Flip: F_Cu -> B_Cu
            block = block.replace('(layer "F_Cu")', '(layer "B_Cu")', 1)
            block = block.replace('(layer F.Cu)', '(layer B.Cu)', 1)
            return block

        text, count = _rewrite_sexpr_blocks(text, "(footprint ", _flip_footprint)
        if count:
            pcb_path.write_text(text, encoding="utf-8")
        return count
    except Exception:
        return 0


def _resize_board_edge_cuts(pcb_path: Path, scale: float) -> tuple[float, float] | None:
    """Scale the Edge_Cuts rectangle by `scale` (e.g. 1.10 for +10%).
    Returns the new (width, height) or None on failure."""
    if not pcb_path.exists():
        return None
    try:
        text = pcb_path.read_text(encoding="utf-8")
        bbox = _extract_edge_bbox(text)
        if bbox is None:
            return None
        min_x, min_y, max_x, max_y = bbox
        old_w = max_x - min_x
        old_h = max_y - min_y
        new_w = old_w * scale
        new_h = old_h * scale
        # Center expansion: shift edges outward equally
        dx = (new_w - old_w) / 2
        dy = (new_h - old_h) / 2
        new_min_x = round(min_x - dx, 2)
        new_min_y = round(min_y - dy, 2)
        new_max_x = round(max_x + dx, 2)
        new_max_y = round(max_y + dy, 2)

        def _map_x(x: float) -> float:
            if abs(x - min_x) < 0.1:
                return new_min_x
            if abs(x - max_x) < 0.1:
                return new_max_x
            return x

        def _map_y(y: float) -> float:
            if abs(y - min_y) < 0.1:
                return new_min_y
            if abs(y - max_y) < 0.1:
                return new_max_y
            return y

        def _replace_edge(block: str) -> str:
            if "Edge.Cuts" not in block and "Edge_Cuts" not in block:
                return block
            start = re.search(r"\(start\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
            end = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
            if not start or not end:
                return block
            x1, y1 = float(start.group(1)), float(start.group(2))
            x2, y2 = float(end.group(1)), float(end.group(2))
            nx1 = new_min_x if abs(x1 - min_x) < 0.1 else (new_max_x if abs(x1 - max_x) < 0.1 else x1)
            ny1 = new_min_y if abs(y1 - min_y) < 0.1 else (new_max_y if abs(y1 - max_y) < 0.1 else y1)
            nx2 = new_min_x if abs(x2 - min_x) < 0.1 else (new_max_x if abs(x2 - max_x) < 0.1 else x2)
            ny2 = new_min_y if abs(y2 - min_y) < 0.1 else (new_max_y if abs(y2 - max_y) < 0.1 else y2)
            block = re.sub(r"\(start\s+[-\d.]+\s+[-\d.]+\)", f"(start {nx1} {ny1})", block, count=1)
            block = re.sub(r"\(end\s+[-\d.]+\s+[-\d.]+\)", f"(end {nx2} {ny2})", block, count=1)
            return block

        text, changed = _rewrite_sexpr_blocks(text, "(gr_line", _replace_edge)
        if not changed:
            return None
        pcb_path.write_text(text, encoding="utf-8")
        return round(new_w, 1), round(new_h, 1)
    except Exception:
        return None


class PipelineState:
    """In-memory + on-disk progress tracker."""

    def __init__(self) -> None:
        self.started_at = _iso()
        self.phases: list[dict[str, Any]] = []
        self.status = "running"
        self.current_phase: str | None = None
        self.final_artifact: str | None = None
        self.hitl_blocker: dict[str, Any] | None = None
        self.error_details: str | None = None
        PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._flush()

    def begin(self, name: str) -> None:
        self.current_phase = name
        self.phases.append({
            "name": name,
            "status": "running",
            "duration_s": 0.0,
            "repair_attempts": 0,
            "notes": "",
            "started_at": _iso(),
        })
        self._flush()

    def update_notes(self, msg: str, *, repair: bool = False) -> None:
        if not self.phases:
            return
        ph = self.phases[-1]
        if repair:
            ph["repair_attempts"] = int(ph.get("repair_attempts", 0)) + 1
        ph["notes"] = (ph["notes"] + "\n" + msg).strip() if ph["notes"] else msg
        self._flush()

    def finish(self, status: str, duration_s: float) -> None:
        if not self.phases:
            return
        ph = self.phases[-1]
        ph["status"] = status
        ph["duration_s"] = round(duration_s, 2)
        ph["ended_at"] = _iso()
        self._flush()

    def end_run(self, status: str, *, artifact: str | None = None,
                hitl: dict[str, Any] | None = None,
                error_details: str | None = None) -> None:
        self.status = status
        self.current_phase = None
        if artifact:
            self.final_artifact = artifact
        if hitl:
            self.hitl_blocker = hitl
        if error_details:
            self.error_details = error_details
        self._flush()

    def _flush(self) -> None:
        progress_percent = self._progress_percent()
        PROGRESS_FILE.write_text(
            json.dumps({
                "schema": "PIPELINE_PROGRESS_V1",
                "status": self.status,
                "current_phase": self.current_phase,
                "progress_percent": progress_percent,
                "status_message": self._status_message(progress_percent),
                "phases": self.phases,
                "final_artifact": self.final_artifact,
                "hitl_blocker": self.hitl_blocker,
                "error_details": self.error_details,
                "started_at": self.started_at,
                "updated_at": _iso(),
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _progress_percent(self) -> int:
        if self.status == "completed":
            return 100
        if self.status == "failed":
            return max(1, min(99, self._completed_weight()))
        if self.status == "awaiting_human":
            return max(1, min(99, self._completed_weight()))
        completed = self._completed_weight()
        if self.current_phase:
            current_weight = PHASE_PROGRESS_WEIGHTS.get(self.current_phase, 5)
            completed += max(1, current_weight // 5)
        return max(0, min(99, completed))

    def _completed_weight(self) -> int:
        total = 0
        for phase in self.phases:
            status = str(phase.get("status", ""))
            if status in {"success", "success_fallback", "review"}:
                total += PHASE_PROGRESS_WEIGHTS.get(str(phase.get("name", "")), 0)
        return total

    def _status_message(self, progress_percent: int) -> str:
        if self.status == "awaiting_human":
            return "Kullanıcı kararı bekleniyor"
        if self.status == "failed":
            return "Pipeline durdu, hata ayrıntısı aşağıda"
        if self.status == "completed":
            return "Pipeline tamamlandı"
        if self.current_phase:
            return PHASE_STATUS_MESSAGES.get(self.current_phase, self.current_phase)
        return f"Pipeline çalışıyor ({progress_percent}%)"


def _emit_hitl(state: PipelineState, *, blocker_type: str, question: str,
               context: dict[str, Any], choices: list[dict[str, str]]) -> dict[str, Any]:
    """Wrap engine.hitl_manager.emit_blocker so the orchestrator records the
    blocker into its progress file and exits cleanly."""
    sys.path.insert(0, str(ROOT))
    from engine.hitl_manager import emit_blocker
    blk = emit_blocker(
        blocker_type=blocker_type,
        question=question,
        context=context,
        suggested_choices=choices,
    )
    if blk.get("status") == "auto_decided":
        answer = blk.get("answer") or {}
        state.update_notes(
            f"HITL auto decision accepted: {answer.get('decision', 'bypass')} - "
            f"{answer.get('rationale', '')}"
        )
        return blk
    state.end_run("awaiting_human", hitl=blk)
    return blk


def _clear_stale_hitl() -> None:
    path = ROOT / "assets" / "generated" / "hitl_state.json"
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _consume_hitl_answer(*, allowed: set[str] | None = None) -> dict[str, Any] | None:
    path = ROOT / "assets" / "generated" / "hitl_answer.json"
    if not path.exists():
        return None
    try:
        answer = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    decision = str(answer.get("decision") or answer.get("resolution") or "")
    if allowed is not None and decision not in allowed:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return answer


def _write_crash_progress(exc: BaseException) -> None:
    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    data: dict[str, Any] = {
        "schema": "PIPELINE_PROGRESS_V1",
        "status": "failed",
        "current_phase": None,
        "progress_percent": 0,
        "status_message": "Pipeline beklenmeyen hata ile durdu",
        "phases": [],
        "final_artifact": None,
        "hitl_blocker": None,
        "error_details": details,
        "started_at": _iso(),
        "updated_at": _iso(),
    }
    if PROGRESS_FILE.exists():
        try:
            existing = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                data.update(existing)
                data["status"] = "failed"
                data["current_phase"] = None
                data["status_message"] = "Pipeline beklenmeyen hata ile durdu"
                data["error_details"] = details
                data["updated_at"] = _iso()
        except Exception:
            pass
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Phase 1: AI synthesis
# ──────────────────────────────────────────────────────────────────────────────
def phase_ai_synthesis(state: PipelineState, args: argparse.Namespace) -> bool:
    state.begin("ai_synthesis")
    t0 = time.time()
    for attempt in range(1, MAX_REPAIR_ATTEMPTS + 1):
        if attempt > 1:
            state.update_notes(f"retry attempt {attempt}/{MAX_REPAIR_ATTEMPTS}", repair=True)
        input_dir = ROOT / ".cache" / "ai_synthesis"
        input_dir.mkdir(parents=True, exist_ok=True)
        stamp = int(time.time() * 1_000_000)
        request_file = input_dir / f"orchestrator_request_{stamp}.txt"
        bom_file = input_dir / f"orchestrator_bom_{stamp}.csv"
        notes_file = input_dir / f"orchestrator_notes_{stamp}.txt"
        request_file.write_text(args.request or "", encoding="utf-8")
        bom_file.write_text(args.bom_text or "", encoding="utf-8")
        notes_file.write_text(args.notes or "", encoding="utf-8")
        cmd = [sys.executable, str(ROOT / "engine" / "run_ai_synthesis.py"),
               "--request-file", str(request_file),
               "--bom-file", str(bom_file),
               "--notes-file", str(notes_file),
               "--project-root", str(ROOT)]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
        # Find the last JSON line in stdout
        out_line = ""
        for line in (r.stdout or "").splitlines():
            if line.strip().startswith("{") and line.strip().endswith("}"):
                out_line = line
        if not out_line:
            state.update_notes("no JSON result emitted by run_ai_synthesis.py")
            continue
        try:
            result = json.loads(out_line)
        except json.JSONDecodeError as e:
            state.update_notes(f"JSON parse failed: {e}")
            continue
        if result.get("success") and result.get("synthesis_source") == "real_ai":
            state.update_notes(
                f"real_ai OK — {result.get('provider')}/{result.get('model')} "
                f"in {result.get('elapsed_seconds', '?')}s"
            )
            state.finish("success", time.time() - t0)
            return True
        if result.get("success"):
            state.update_notes(
                f"deterministic_fallback used (AI error: {result.get('ai_error', '?')[:120]})"
            )
            if attempt < MAX_REPAIR_ATTEMPTS:
                continue
            # Fallback netlist is still usable for downstream phases.
            state.finish("success_fallback", time.time() - t0)
            return True
    # All attempts failed
    state.finish("failed", time.time() - t0)
    _emit_hitl(
        state,
        blocker_type="constraint",
        question=("AI synthesis failed after 3 attempts. The provider may be down or quota exhausted. "
                  "How should the pipeline proceed?"),
        context={"phase": "ai_synthesis", "attempts": MAX_REPAIR_ATTEMPTS},
        choices=[
            {"id": "switch", "label": "Switch provider (Ollama local / Claude)",
             "consequence": "Engineer updates ai_settings.json, restart pipeline"},
            {"id": "fallback", "label": "Accept deterministic fallback",
             "consequence": "Use the engineered template netlist as ground truth"},
            {"id": "abort", "label": "Abort run",
             "consequence": "No netlist produced; nothing downstream runs"},
        ],
    )
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Phase 2: KiCad project generation
# ──────────────────────────────────────────────────────────────────────────────
def phase_design_feasibility(state: PipelineState) -> bool:
    state.begin("design_feasibility")
    t0 = time.time()
    sys.path.insert(0, str(ROOT / "engine"))
    from design_feasibility_service import DesignFeasibilityService

    output = ROOT / "assets" / "generated" / "design_feasibility_report.json"
    report = DesignFeasibilityService().audit(
        NETLIST_PATH,
        output=output,
        bom_file=ROOT / "BOM.csv",
        config_file=ROOT / "project_config.json",
    )
    state.update_notes(report.blocker_summary)

    # Log density details
    if report.auto_layer_upgrade:
        state.update_notes(
            f"\u26a0 Yoğunluk={report.density_ratio * 100:.1f}%: "
            f"Katman sayısı otomatik olarak {report.suggested_layer_count}'e yükseltildi."
        )
    if report.suggested_board_area_mm2 > 0:
        state.update_notes(
            f"Önerilen minimum kart alanı: {report.suggested_board_area_mm2:.0f} mm²"
        )
    if report.status != "blocked":
        state.finish("success" if report.status == "pass" else "review", time.time() - t0)
        return True
    state.finish("failed", time.time() - t0)
    _emit_hitl(
        state,
        blocker_type="placement",
        question=(
            "Pre-KiCad feasibility gate blocked the design. The requested electrical scope "
            "does not fit the requested PCB envelope with production keepouts. Choose an "
            "engineering correction before KiCad/Freerouting runs."
        ),
        context={
            "phase": "design_feasibility",
            "report": str(output),
            "summary": report.blocker_summary,
            "board_size_mm": list(report.board_size_mm),
            "pcb_mounted_count": report.pcb_mounted_count,
            "estimated_routing_utilization": report.estimated_routing_utilization,
            "fixed_board_constraint": report.fixed_board_constraint,
            "high_risk_blocks": report.high_risk_blocks,
            "optional_reduction_candidates": report.optional_reduction_candidates,
        },
        choices=[
            {"id": action.id, "label": action.label, "consequence": action.consequence}
            for action in report.recommended_actions
        ],
    )
    return False


def phase_component_resolution(state: PipelineState) -> bool:
    state.begin("component_resolution")
    t0 = time.time()
    try:
        sys.path.insert(0, str(ROOT))
        from engine.netlist_source_normalizer import ComponentResolver

        if not NETLIST_PATH.exists():
            state.update_notes(f"netlist missing: {NETLIST_PATH}")
            state.finish("failed", time.time() - t0)
            return False
        data = json.loads(NETLIST_PATH.read_text(encoding="utf-8"))
        components = [c for c in data.get("components", []) if isinstance(c, dict)]
        results = ComponentResolver(ROOT).resolve_missing_footprints(components)
        if components != data.get("components", []):
            data["components"] = components
            NETLIST_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        unresolved = [item for item in results if not item.found]
        resolved = [item for item in results if item.found]
        state.update_notes(
            f"component resolver: resolved={len(resolved)}, unresolved={len(unresolved)}"
        )
        if not unresolved:
            state.finish("success", time.time() - t0)
            return True
        answer = _consume_hitl_answer(
            allowed={"approve_placeholder", "provide_library", "abort"}
        )
        if answer:
            decision = str(answer.get("decision", ""))
            rationale = str(answer.get("rationale", "")).strip()
            if decision == "approve_placeholder":
                state.update_notes(
                    "Kullanıcı geçici footprint/pin onayı verdi; production gate review olarak devam ediliyor."
                    + (f" Gerekçe: {rationale}" if rationale else "")
                )
                state.finish("review", time.time() - t0)
                return True
            if decision == "abort":
                state.update_notes("Kullanıcı component resolver aşamasında pipeline'ı durdurdu.")
                state.finish("failed", time.time() - t0)
                return False
            state.update_notes(
                "Kullanıcı kütüphane dosyası ekleneceğini belirtti; footprint çözümü yeniden kontrol ediliyor."
            )
        state.update_notes(
            "unresolved footprint review required: "
            + ", ".join(f"{item.ref}({item.mpn})" for item in unresolved[:6])
        )
        blk = _emit_hitl(
            state,
            blocker_type="bom",
            question=(
                "Bazı bileşenlerin footprint/pin yapısı otomatik çözülemedi. "
                "Nasıl devam edelim?"
            ),
            context={
                "phase": "component_resolution",
                "report": str(ROOT / "assets" / "generated" / "missing_footprints_report.json"),
                "unresolved": [
                    {
                        "ref": item.ref,
                        "mpn": item.mpn,
                        "requested_footprint": item.requested_footprint,
                        "error": item.error,
                    }
                    for item in unresolved
                ],
            },
            choices=[
                {"id": "approve_placeholder", "label": "Geçici footprint ile devam et",
                 "consequence": "Pipeline devam eder; production gate bu kararı review olarak işaretler"},
                {"id": "provide_library", "label": "Kütüphane dosyası ekledim, tekrar dene",
                 "consequence": "Resolver yeniden çalışır; footprint bulunursa otomatik devam eder"},
                {"id": "abort", "label": "Durdur",
                 "consequence": "BOM/MPN veya footprint netleşmeden ilerlenmez"},
            ],
        )
        if blk.get("status") == "auto_decided":
            state.finish("review", time.time() - t0)
            return True
        state.finish("failed", time.time() - t0)
        return False
    except Exception as exc:  # noqa: BLE001
        state.update_notes(f"component resolver failed: {exc}")
        state.finish("failed", time.time() - t0)
        return False


def phase_kicad_generation(state: PipelineState) -> bool:
    state.begin("kicad_generation")
    t0 = time.time()
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(ROOT / "tool" / "run_kicad_phase2.ps1"),
           "-Export", "-ContinueOnDrcError"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900, cwd=str(ROOT))
    pcb_file, drc_file, manufacturing_dir = _current_artifacts()
    pcb_is_real = False
    if pcb_file.exists():
        pcb_text = pcb_file.read_text(encoding="utf-8", errors="ignore")
        pcb_is_real = "(footprint" in pcb_text and "pcbnew unavailable" not in pcb_text
    if pcb_is_real and drc_file.exists():
        state.update_notes(
            f"PCB/DRC written: {pcb_file.name}; manufacturing={manufacturing_dir}; "
            f"kicad_exit={r.returncode}"
        )
        state.finish("success", time.time() - t0)
        return True
    tail = (r.stderr or r.stdout or "")[-800:]
    state.update_notes(f"exit={r.returncode}; tail: {tail}")
    state.finish("failed", time.time() - t0)
    if "Placement infeasible" in tail:
        question = (
            "KiCad placement blocked the design: current BOM/netlist cannot fit on the "
            "requested board with the AC, RF, relay, socket, and keepout constraints. "
            "Choose an engineering correction before production export."
        )
        choices = [
            {"id": "allow_larger_board", "label": "Allow larger PCB",
             "consequence": "Relax board-size constraint and re-place with the same circuit scope"},
            {"id": "reduce_scope", "label": "Reduce optional scope",
             "consequence": "Remove/suppress optional headers, test points, or noncritical modules before rerun"},
            {"id": "split_board", "label": "Split into boards",
             "consequence": "Separate AC/relay power from RF/logic board and rerun architecture"},
            {"id": "abort", "label": "Abort", "consequence": "Stop pipeline"},
        ]
    else:
        question = "KiCad project generation failed. Likely cause: missing/invalid footprint, symbol mapping, or KiCad CLI error."
        choices = [
            {"id": "retry", "label": "Retry after engineer fixes BOM/netlist",
             "consequence": "Engineer corrects component refs; re-run pipeline"},
            {"id": "abort", "label": "Abort", "consequence": "Stop pipeline"},
        ]
    if getattr(state, "suppress_hitl", False):
        return False
    _emit_hitl(
        state, blocker_type="constraint",
        question=question,
        context={"phase": "kicad_generation", "stderr_tail": tail},
        choices=choices,
    )
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Phase 3: DRC cleanup (prune + zone fill)
# ──────────────────────────────────────────────────────────────────────────────
def _run_kicad_python(script: Path, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run([KPY, str(script)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def phase_drc_cleanup(state: PipelineState) -> bool:
    state.begin("drc_cleanup")
    t0 = time.time()
    pcb_file, drc_file, manufacturing_dir = _current_artifacts()
    missing = [
        str(path)
        for path in (
            pcb_file,
            drc_file,
        )
        if not path.exists()
    ]
    if missing:
        state.update_notes(f"production artifacts missing: {' | '.join(missing)}")
        state.finish("failed", time.time() - t0)
        return False
    state.update_notes(
        "Freerouting + prune + zone-fill cleanup running before DRC verification. "
        "Gerber/drill/PnP export waits for clean DRC."
    )
    # NOTE: We do NOT strip pre-existing tracks before Freerouting.  Empirical
    # result: stripping caused Freerouting (-mp 100) to leave 85 nets
    # unconnected, while passing Phase 2's pre-routes through let it finish
    # with 0 unconnected and only 21 DRC items.

    # ── STEP A: Freerouting auto-router (the missing piece) ──────────────────
    # KiCad's CLI does not include an auto-router. Freerouting (open-source,
    # community-maintained) fills this gap.  It exports DSN, routes, and
    # imports SES back into the board.
    fr_script = ROOT / "engine" / "_route_with_freerouting.py"
    fr_jar = ROOT / "tools" / "freerouting.jar"
    if fr_script.exists() and fr_jar.exists():
        # -mt 1 = single-threaded (avoids the multi-thread clearance-violation bug).
        # -mp 500 = aggressive optimization (more passes = fewer remaining DRC issues).
        env = {**os.environ, "FR_THREADS": "1", "FR_MAX_PASSES": "500"}
        r = subprocess.run(
            [KPY, str(fr_script)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900, env=env,
        )
        added = 0
        for ln in (r.stdout or "").splitlines():
            if "after:" in ln and "delta:" in ln:
                # parse "[FR] after: NNN tracks  (delta: +NN)"
                try:
                    added = int(ln.split("delta:")[1].split(")")[0].strip().lstrip("+"))
                except (IndexError, ValueError):
                    added = 0
                break
        state.update_notes(f"freerouting routed +{added} tracks (exit={r.returncode})")
    else:
        state.update_notes("freerouting jar/script missing; skipping auto-route")

    # ── STEP B: Prune any residual dangling copper ───────────────────────────
    prune_script = ROOT / "engine" / "_prune_one.py"
    if not prune_script.exists():
        state.update_notes("_prune_one.py missing; skipping prune")
    else:
        total = 0
        for p in range(1, 9):
            r = _run_kicad_python(prune_script, timeout=60)
            removed = 0
            for ln in (r.stdout or "").splitlines():
                if ln.startswith("REMOVED="):
                    try:
                        removed = int(ln.split("=", 1)[1])
                    except ValueError:
                        removed = -1
                    break
            if removed <= 0:
                break
            total += removed
        state.update_notes(f"prune removed {total} dangling item(s) across passes")

    # ── STEP C: Zone fill ────────────────────────────────────────────────────
    zf_script = ROOT / "engine" / "_zone_fill.py"
    if zf_script.exists():
        r = _run_kicad_python(zf_script, timeout=120)
        state.update_notes(f"zone fill exit={r.returncode}")
    state.finish("success", time.time() - t0)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Phase 4: DRC verify
# ──────────────────────────────────────────────────────────────────────────────
def phase_drc_verify(state: PipelineState) -> bool:
    ans_file = ROOT / "assets" / "generated" / "hitl_answer.json"
    if ans_file.exists():
        try:
            ans = json.loads(ans_file.read_text(encoding="utf-8"))
            if ans.get("resolution") == "force_pack" or ans.get("decision") == "force_pack":
                ans_file.unlink()
                state.update_notes("HITL override: forced pack with DRC violations")
                state.finish("success", 0)
                return True
        except Exception:
            pass

    state.begin("drc_verify")
    t0 = time.time()
    pcb_file, drc_file, _manufacturing_dir = _current_artifacts()
    drc_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = [KCLI, "pcb", "drc", "--format", "json", "--all-track-errors",
           "--schematic-parity", "--output", str(drc_file), str(pcb_file)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    if not drc_file.exists():
        state.update_notes(f"DRC report not produced (exit={r.returncode})")
        state.finish("failed", time.time() - t0)
        return False
    rep = json.loads(drc_file.read_text(encoding="utf-8"))
    viols = rep.get("violations", [])
    schematic = rep.get("schematic_parity", [])
    unconn = rep.get("unconnected_items", [])
    assembly_review_types = {
        "courtyards_overlap",
        "silk_overlap",
        "silk_edge_clearance",
        "silk_over_copper",
        "pth_inside_courtyard",
    }
    critical_viols = [
        v for v in viols
        if not (
            (v.get("severity") == "warning" and v.get("type") in ("schematic_parity", "starved_thermal"))
            or v.get("type") in assembly_review_types
        )
    ]
    assembly_review = [v for v in viols if v.get("type") in assembly_review_types]
    
    critical_schematic = [s for s in schematic if s.get("severity") == "error"]

    state.update_notes(
        f"violations={len(viols)} (critical={len(critical_viols)}, assembly_review={len(assembly_review)}), "
        f"schematic_parity={len(critical_schematic)} (ignored={len(schematic) - len(critical_schematic)}), unconnected={len(unconn)}"
    )
    if not critical_viols and not critical_schematic and not unconn:
        state.finish("success", time.time() - t0)
        return True
    state.finish("failed", time.time() - t0)
    if getattr(state, "suppress_hitl", False):
        return False
    # Categorize violations to provide actionable HITL question
    types: dict[str, int] = {}
    for v in critical_viols:
        types[v.get("type", "?")] = types.get(v.get("type", "?"), 0) + 1
    for v in schematic:
        types[v.get("type", "schematic_parity")] = types.get(v.get("type", "schematic_parity"), 0) + 1
    _emit_hitl(
        state, blocker_type="routing",
        question=(f"DRC verify found {len(critical_viols)} violation(s), {len(schematic)} schematic parity item(s), and {len(unconn)} unconnected item(s) "
                  "after auto-cleanup. These require routing decisions the auto-pipeline cannot safely make."),
        context={"phase": "drc_verify", "violation_types": types,
                 "unconnected_count": len(unconn),
                 "drc_report": str(drc_file)},
        choices=[
            {"id": "manual_route", "label": "Open in KiCad GUI and route manually",
             "consequence": "Engineer fixes layout; re-run pipeline from drc_verify"},
            {"id": "force_pack", "label": "Force-pack ZIP anyway (NOT recommended)",
             "consequence": "Production ZIP with known issues; explicit override"},
            {"id": "abort", "label": "Abort and investigate",
             "consequence": "Stop here, review DRC report manually"},
        ],
    )
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Phase 5: Manifest sign
# ──────────────────────────────────────────────────────────────────────────────
def phase_manifest_sign(state: PipelineState) -> bool:
    state.begin("manifest_sign")
    t0 = time.time()
    env = {"PYTHONPATH": str(ROOT / "engine")}
    pcb_file, drc_file, _manufacturing_dir = _current_artifacts()
    cmd = [
        KPY,
        str(ROOT / "engine" / "board_verification_manifest.py"),
        "--pcb-file",
        str(pcb_file),
        "--drc-report-file",
        str(drc_file),
        "--netlist-file",
        str(NETLIST_PATH),
        "--bom-file",
        "BOM.csv",
        "--output",
        "outputs/engineering/board_verification_manifest.json",
        "--asset-output",
        "assets/generated/board_verification_manifest.json",
    ]
    full_env = {**os.environ, **env}
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120, env=full_env, cwd=str(ROOT))
    state.update_notes(f"exit={r.returncode}")
    if r.returncode == 0:
        state.finish("success", time.time() - t0)
        return True
    state.finish("failed", time.time() - t0)
    _emit_hitl(
        state, blocker_type="constraint",
        question=f"Manifest signing failed: {(r.stderr or r.stdout)[-200:]}",
        context={"phase": "manifest_sign", "stderr_tail": (r.stderr or "")[-500:]},
        choices=[
            {"id": "abort", "label": "Abort", "consequence": "Stop pipeline"},
        ],
    )
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Phase 6: Fabrication ZIP
# ──────────────────────────────────────────────────────────────────────────────
def phase_fab_package(state: PipelineState) -> bool:
    state.begin("fab_package")
    t0 = time.time()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "engine")}
    pcb_file, drc_file, manufacturing_dir = _current_artifacts()
    cmd = [KPY, str(ROOT / "engine" / "fabrication_api_service.py"),
           "--quantity", "5", "--manufacturer", "PCBWay",
           "--solder-mask-color", "Green",
           "--phase4-dir", str(manufacturing_dir),
           "--pcb-file", str(pcb_file),
           "--drc-report-file", str(drc_file),
           "--verification-manifest-file", "assets/generated/board_verification_manifest.json",
           "--asset-output", "assets/generated/fabrication_package.json"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=300, env=env, cwd=str(ROOT))
    if r.returncode == 0 and FAB_ZIP_PATH.exists():
        size = FAB_ZIP_PATH.stat().st_size
        state.update_notes(f"ZIP packed: {size:,} bytes")
        state.finish("success", time.time() - t0)
        return True
    state.update_notes(f"exit={r.returncode}; tail: {(r.stderr or r.stdout or '')[-300:]}")
    state.finish("failed", time.time() - t0)
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description="OmniCircuit full pipeline orchestrator")
    p.add_argument("--request", default="", help="User design request (free text)")
    p.add_argument("--bom-file", default="", help="BOM CSV path")
    p.add_argument("--notes", default="", help="Technical notes")
    p.add_argument("--skip-synthesis", action="store_true",
                   help="Reuse existing netlist; skip Phase 1")
    args = p.parse_args()

    # Inline BOM content from file if provided
    args.bom_text = ""
    if args.bom_file:
        bf = Path(args.bom_file)
        if bf.exists():
            args.bom_text = bf.read_text(encoding="utf-8")

    state = PipelineState()
    _clear_stale_hitl()
    print(f"[ORCH] starting full pipeline at {state.started_at}", flush=True)

    phases: list[tuple[str, Callable[[PipelineState], bool]]] = [
        ("manifest_sign", phase_manifest_sign),
        ("fab_package", phase_fab_package),
    ]

    if not args.skip_synthesis:
        if not phase_ai_synthesis(state, args):
            return 2  # awaiting_human emitted

    if not phase_design_feasibility(state):
        if state.hitl_blocker:
            print("[ORCH] paused at design_feasibility - HITL blocker emitted", flush=True)
            return 2
        print("[ORCH] failed at design_feasibility", flush=True)
        state.end_run("failed")
        return 1
    print("[ORCH] design_feasibility OK", flush=True)

    if not phase_component_resolution(state):
        if state.hitl_blocker:
            print("[ORCH] paused at component_resolution - HITL blocker emitted", flush=True)
            return 2
        print("[ORCH] failed at component_resolution", flush=True)
        state.end_run("failed")
        return 1
    print("[ORCH] component_resolution OK", flush=True)

    routing_ok = False
    expected_board_size_mm: tuple[float, float] | None = None
    last_failure: dict[str, Any] | None = None
    correction_strategies = [
        ("baseline", "Mevcut yerlesim ve yonlendirme"),
        ("via_shrink", "Via boyutunu kucultme (0.25/0.5mm)"),
        ("passives_to_back", "Pasif bilesenleri (R,C) arka yuze tasima"),
        ("board_resize_10", "Kart boyutunu %10 buyutme"),
        ("board_resize_20", "Kart boyutunu %20 buyutme"),
    ]

    for attempt_index, (strategy, description) in enumerate(correction_strategies):
        state.suppress_hitl = True
        print(
            f"[ORCH] routing deneme {attempt_index + 1}/{len(correction_strategies)}: {description}",
            flush=True,
        )
        state.update_notes(f"Routing deneme #{attempt_index + 1}: {description}")

        if not phase_kicad_generation(state):
            last_failure = {"phase": "kicad_generation", "hitl": state.hitl_blocker}
            continue

        pcb_file, _drc_file, _mfg = _current_artifacts()
        safe_snapshot = _snapshot_pcb(pcb_file, f"routing_attempt_{attempt_index + 1}")

        if strategy == "via_shrink":
            ok = _shrink_vias(pcb_file)
            state.update_notes(f"Via kucultme {'basarili' if ok else 'atlandi'}")
        elif strategy == "passives_to_back":
            moved = _move_passives_to_back(pcb_file)
            state.update_notes(f"{moved} pasif bilesen B_Cu katmanina tasindi")
        elif strategy == "board_resize_10":
            result = _resize_board_edge_cuts(pcb_file, BOARD_RESIZE_STEP1)
            if result:
                expected_board_size_mm = result
                state.update_notes(f"Kart boyutu %10 buyutuldu: {result[0]:.1f}x{result[1]:.1f}mm")
            else:
                state.update_notes("Kart boyutu buyutme basarisiz")
        elif strategy == "board_resize_20":
            result = _resize_board_edge_cuts(pcb_file, BOARD_RESIZE_STEP2)
            if result:
                expected_board_size_mm = result
                state.update_notes(f"Kart boyutu %20 buyutuldu: {result[0]:.1f}x{result[1]:.1f}mm")
            else:
                state.update_notes("Kart boyutu buyutme basarisiz")

        if not _validate_absolute_constraints(
            state,
            f"{strategy}_after_generation",
            expected_board_size_mm=expected_board_size_mm,
        ):
            _restore_pcb(safe_snapshot, pcb_file)
            last_failure = {"phase": "absolute_constraints", "constraint": LAST_CONSTRAINT_VIOLATION}
            continue

        if not phase_drc_cleanup(state):
            _restore_pcb(safe_snapshot, pcb_file)
            last_failure = {"phase": "drc_cleanup", "hitl": state.hitl_blocker}
            continue

        if not _validate_absolute_constraints(
            state,
            f"{strategy}_after_cleanup",
            expected_board_size_mm=expected_board_size_mm,
        ):
            _restore_pcb(safe_snapshot, pcb_file)
            last_failure = {"phase": "absolute_constraints", "constraint": LAST_CONSTRAINT_VIOLATION}
            continue

        if phase_drc_verify(state):
            if _validate_absolute_constraints(
                state,
                f"{strategy}_after_drc_verify",
                expected_board_size_mm=expected_board_size_mm,
            ):
                routing_ok = True
                break
            _restore_pcb(safe_snapshot, pcb_file)
            last_failure = {"phase": "absolute_constraints", "constraint": LAST_CONSTRAINT_VIOLATION}
            continue

        _, drc_file, _ = _current_artifacts()
        metrics = _parse_drc_metrics(drc_file)
        last_failure = {
            "phase": "drc_verify",
            "metrics": metrics,
            "drc_report": str(drc_file),
        }
        _restore_pcb(safe_snapshot, pcb_file)
        print(
            f"[ORCH] DRC: violations={metrics['violations']}, "
            f"unconnected={metrics['unconnected']}, critical={metrics['critical']}; "
            "sonraki otonom stratejiye geciliyor...",
            flush=True,
        )

    if not routing_ok:
        state.suppress_hitl = False
        _emit_hitl(
            state,
            blocker_type="routing",
            question=(
                "Otonom routing dongusu 5 denemeden sonra temiz sonuca ulasamadi. "
                "Manuel mudahale gerekiyor."
            ),
            context={
                "phase": "routing_loop",
                "last_failure": last_failure or {},
                "drc_report": str(_current_artifacts()[1]),
            },
            choices=[
                {"id": "manual_route", "label": "KiCad'da manuel duzelt",
                 "consequence": "Muhendis layout'u duzeltir; pipeline tekrar --skip-synthesis ile calisir"},
                {"id": "force_pack", "label": "Force Pack'i acikca onayla",
                 "consequence": "Bilinen sorunlarla uretim ZIP'i uretilir; varsayilan degildir"},
                {"id": "abort", "label": "Durdur",
                 "consequence": "Son raporlar UI'da incelenir"},
            ],
        )
        print("[ORCH] paused at routing_loop - HITL blocker emitted", flush=True)
        return 2

    state.suppress_hitl = False
    _clear_stale_hitl()

    for name, fn in phases:
        ok = fn(state)
        if not ok:
            if state.hitl_blocker:
                print(f"[ORCH] paused at {name} — HITL blocker emitted", flush=True)
                return 2
            print(f"[ORCH] failed at {name}", flush=True)
            state.end_run("failed")
            return 1
        print(f"[ORCH] {name} OK", flush=True)

    state.end_run("completed", artifact=str(FAB_ZIP_PATH))
    print(f"[ORCH] COMPLETED — artifact: {FAB_ZIP_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        _write_crash_progress(exc)
        traceback.print_exc()
        raise SystemExit(1)
