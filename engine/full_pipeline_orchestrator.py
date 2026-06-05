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
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
KCLI = r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
KPY = r"C:\Program Files\KiCad\10.0\bin\python.exe"
PROGRESS_FILE = ROOT / "assets" / "generated" / "pipeline_progress.json"
PROJ = "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
PCB_PATH = ROOT / "outputs" / "kicad" / PROJ / f"{PROJ}.kicad_pcb"
DRC_PATH = ROOT / "outputs" / "kicad" / PROJ / "manufacturing" / "drc_report.json"
NETLIST_PATH = ROOT / "outputs" / "phase1" / "AI_NETLIST_V1.json"
FAB_ZIP_PATH = ROOT / "outputs" / "fabrication" / "Quantum_Mind_Anchor_v2_4_Production.zip"

MAX_REPAIR_ATTEMPTS = 3


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


class PipelineState:
    """In-memory + on-disk progress tracker."""

    def __init__(self) -> None:
        self.started_at = _iso()
        self.phases: list[dict[str, Any]] = []
        self.status = "running"
        self.current_phase: str | None = None
        self.final_artifact: str | None = None
        self.hitl_blocker: dict[str, Any] | None = None
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
                hitl: dict[str, Any] | None = None) -> None:
        self.status = status
        self.current_phase = None
        if artifact:
            self.final_artifact = artifact
        if hitl:
            self.hitl_blocker = hitl
        self._flush()

    def _flush(self) -> None:
        PROGRESS_FILE.write_text(
            json.dumps({
                "schema": "PIPELINE_PROGRESS_V1",
                "status": self.status,
                "current_phase": self.current_phase,
                "phases": self.phases,
                "final_artifact": self.final_artifact,
                "hitl_blocker": self.hitl_blocker,
                "started_at": self.started_at,
                "updated_at": _iso(),
            }, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def _emit_hitl(state: PipelineState, *, blocker_type: str, question: str,
               context: dict[str, Any], choices: list[dict[str, str]]) -> None:
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
    state.end_run("awaiting_human", hitl=blk)


def _clear_stale_hitl() -> None:
    path = ROOT / "assets" / "generated" / "hitl_state.json"
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


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
    report = DesignFeasibilityService().audit(NETLIST_PATH, output=output)
    state.update_notes(report.blocker_summary)
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


def phase_kicad_generation(state: PipelineState) -> bool:
    state.begin("kicad_generation")
    t0 = time.time()
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(ROOT / "tool" / "run_kicad_phase2.ps1"),
           "-Export"]
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
        "routing and zone fill handled by KiCad automation; second Freerouting pass is disabled. "
        "Gerber/drill/PnP export waits for clean DRC."
    )
    state.finish("success", time.time() - t0)
    return True

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
    }
    critical_viols = [
        v for v in viols
        if not (
            (v.get("severity") == "warning" and v.get("type") in ("schematic_parity", "starved_thermal"))
            or v.get("type") in assembly_review_types
        )
    ]
    assembly_review = [v for v in viols if v.get("type") in assembly_review_types]
    
    state.update_notes(
        f"violations={len(viols)} (critical={len(critical_viols)}, assembly_review={len(assembly_review)}), "
        f"schematic_parity={len(schematic)}, unconnected={len(unconn)}"
    )
    if not critical_viols and not schematic and not unconn:
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

    routing_attempts = max(1, int(os.getenv("PIPELINE_ROUTING_ATTEMPTS", "5")))
    routing_ok = False
    last_hitl = None
    for attempt in range(1, routing_attempts + 1):
        state.suppress_hitl = attempt < routing_attempts
        if attempt > 1:
            print(f"[ORCH] routing retry {attempt}/{routing_attempts}", flush=True)
            state.hitl_blocker = None
        for route_name, route_fn in (
            ("kicad_generation", phase_kicad_generation),
            ("drc_cleanup", phase_drc_cleanup),
            ("drc_verify", phase_drc_verify),
        ):
            if route_fn(state):
                print(f"[ORCH] {route_name} OK", flush=True)
                continue
            last_hitl = state.hitl_blocker
            if route_name == "drc_verify" and attempt < routing_attempts:
                print(f"[ORCH] {route_name} retryable; trying another Freerouting result", flush=True)
                break
            if state.hitl_blocker:
                print(f"[ORCH] paused at {route_name} - HITL blocker emitted", flush=True)
                return 2
            print(f"[ORCH] failed at {route_name}", flush=True)
            state.end_run("failed")
            return 1
        else:
            routing_ok = True
            break

    if not routing_ok:
        state.suppress_hitl = False
        state.hitl_blocker = last_hitl
        print("[ORCH] paused at drc_verify - HITL blocker emitted", flush=True)
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
    raise SystemExit(main())
