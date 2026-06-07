"""Human-in-the-Loop (HITL) interaction manager for OmniCircuit AI.

The pipeline must STOP and ask a human engineer whenever it hits:
  - An ambiguous pinout it cannot derive from the BOM/datasheet
  - A spatial routing blocker that auto-routing cannot resolve safely
  - A missing constraint (clearance, layer assignment, impedance target)
  - Any decision that would silently change electrical behavior

This module is the single channel for that escalation.  It writes a JSON
state file the Flutter UI polls, then blocks until a human-answers file
appears (or, in CLI mode, until the engineer responds inline).

Design principles
=================
1. NEVER guess when a decision affects manufacturability or electrical
   correctness.  Ask instead.
2. Every blocker gets a typed enum + a concrete, technical question +
   any context (footprint refs, coordinates, net names) needed to answer.
3. Decisions and rationales are appended to ``hitl_decisions.log`` so the
   audit trail survives across sessions.

JSON contract emitted to ``assets/generated/hitl_state.json``::

    {
      "schema": "HITL_STATE_V1",
      "status": "awaiting_human_input",
      "blocker_type": "routing" | "pinout" | "clearance" | "placement" | "constraint",
      "session_id": "<uuid4>",
      "raised_at": "<iso8601-utc>",
      "context": { ...arbitrary engineer-readable context... },
      "question": "<one specific technical question>",
      "suggested_choices": [
          {"id": "A", "label": "...", "consequence": "..."},
          ...
      ],
      "answer_path": "assets/generated/hitl_answer.json"
    }

When the Flutter UI (or a CLI engineer) writes
``assets/generated/hitl_answer.json``::

    {
      "session_id": "<same uuid>",
      "decision": "A",  # or free-text
      "rationale": "<engineer's reasoning>",
      "decided_at": "<iso8601-utc>"
    }

``ask_human_engineer()`` returns that dict.
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from engine.omnicircuit_improvements import check_pre_defined_decision
except Exception:  # noqa: BLE001
    try:
        from omnicircuit_improvements import check_pre_defined_decision
    except Exception:  # noqa: BLE001
        check_pre_defined_decision = None  # type: ignore[assignment]

# UTF-8 stdout for Turkish messages
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8")


HITL_STATE_FILE = Path("assets/generated/hitl_state.json")
HITL_ANSWER_FILE = Path("assets/generated/hitl_answer.json")
HITL_LOG_FILE = Path("assets/generated/hitl_decisions.log")

VALID_BLOCKER_TYPES = {"routing", "pinout", "clearance", "placement", "constraint", "bom"}


def _iso_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_dirs() -> None:
    HITL_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)


def _auto_decision_for_blocker(
    *,
    blocker_type: str,
    question: str,
    context: dict[str, Any],
    suggested_choices: Iterable[dict[str, str]] | None,
) -> dict[str, Any] | None:
    if check_pre_defined_decision is None:
        return None
    try:
        decision = check_pre_defined_decision(
            question + "\n" + json.dumps(context, ensure_ascii=False)
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[HITL] predefined decision check failed: {exc}", file=sys.stderr)
        return None
    if not decision:
        return None

    _ensure_dirs()
    answer_value = str(decision.get("decision") or decision.get("answer") or "bypass")
    state = {
        "schema": "HITL_STATE_V1",
        "status": "auto_decided",
        "blocker_type": blocker_type,
        "session_id": str(uuid.uuid4()),
        "raised_at": _iso_utc(),
        "context": context,
        "question": question,
        "suggested_choices": list(suggested_choices or []),
        "answer_path": str(HITL_ANSWER_FILE),
        "auto_decision": True,
    }
    answer = {
        "session_id": state["session_id"],
        "decision": answer_value,
        "rationale": str(decision.get("rationale") or ""),
        "decided_at": _iso_utc(),
        "automatic": True,
    }
    state["answer"] = answer
    _append_log(state, answer)
    try:
        if HITL_STATE_FILE.exists():
            HITL_STATE_FILE.unlink()
    except FileNotFoundError:
        pass
    print(f"[HITL] AUTO-DECISION ({blocker_type}) -> {answer_value}", file=sys.stderr)
    print(f"[HITL] Rationale: {answer['rationale']}", file=sys.stderr)
    return state


def emit_blocker(
    *,
    blocker_type: str,
    question: str,
    context: dict[str, Any],
    suggested_choices: Iterable[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Write the blocker state JSON the UI polls.  Returns the state dict."""
    if blocker_type not in VALID_BLOCKER_TYPES:
        raise ValueError(
            f"blocker_type must be one of {sorted(VALID_BLOCKER_TYPES)}, got {blocker_type!r}"
        )
    auto_state = _auto_decision_for_blocker(
        blocker_type=blocker_type,
        question=question,
        context=context,
        suggested_choices=suggested_choices,
    )
    if auto_state is not None:
        return auto_state

    _ensure_dirs()
    state = {
        "schema": "HITL_STATE_V1",
        "status": "awaiting_human_input",
        "blocker_type": blocker_type,
        "session_id": str(uuid.uuid4()),
        "raised_at": _iso_utc(),
        "context": context,
        "question": question,
        "suggested_choices": list(suggested_choices or []),
        "answer_path": str(HITL_ANSWER_FILE),
    }
    HITL_STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # Mirror to stderr so a CLI engineer also sees it
    print(f"[HITL] BLOCKER ({blocker_type}) — answer at {HITL_ANSWER_FILE}", file=sys.stderr)
    print(f"[HITL] Question: {question}", file=sys.stderr)
    return state


def wait_for_answer(
    state: dict[str, Any],
    *,
    poll_interval_s: float = 1.0,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """Block until the matching answer file appears, then return its dict.

    A previous unmatched answer is ignored (must match session_id).
    """
    expected_sid = state["session_id"]
    start = time.time()
    while True:
        if HITL_ANSWER_FILE.exists():
            try:
                ans = json.loads(HITL_ANSWER_FILE.read_text(encoding="utf-8"))
                if ans.get("session_id") == expected_sid:
                    _append_log(state, ans)
                    # Clear the state file so UI knows the blocker is resolved
                    try:
                        HITL_STATE_FILE.unlink()
                    except FileNotFoundError:
                        pass
                    return ans
            except json.JSONDecodeError:
                pass  # partial write; keep polling
        if timeout_s is not None and (time.time() - start) > timeout_s:
            raise TimeoutError(
                f"HITL answer not received within {timeout_s}s for session {expected_sid}"
            )
        time.sleep(poll_interval_s)


def ask_human_engineer(
    *,
    blocker_type: str,
    question: str,
    context: dict[str, Any] | None = None,
    suggested_choices: Iterable[dict[str, str]] | None = None,
    timeout_s: float | None = None,
) -> dict[str, Any]:
    """One-shot: emit blocker, wait for answer, return engineer's decision."""
    state = emit_blocker(
        blocker_type=blocker_type,
        question=question,
        context=context or {},
        suggested_choices=suggested_choices,
    )
    if state.get("status") == "auto_decided":
        return dict(state.get("answer") or {})
    return wait_for_answer(state, timeout_s=timeout_s)


def _append_log(state: dict[str, Any], answer: dict[str, Any]) -> None:
    _ensure_dirs()
    entry = {
        "session_id": state["session_id"],
        "blocker_type": state["blocker_type"],
        "raised_at": state["raised_at"],
        "decided_at": answer.get("decided_at"),
        "question": state["question"],
        "context": state["context"],
        "decision": answer.get("decision"),
        "rationale": answer.get("rationale"),
    }
    with open(HITL_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# CLI demo / smoke test
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # When invoked directly, just emit a demonstration blocker and exit
    # (don't block) so the Flutter UI / engineer can see the contract.
    demo = emit_blocker(
        blocker_type="placement",
        question=(
            "DevKit ESP32-S3-DevKitC-1 sockets (28×56mm) do not fit at the "
            "current U1 SMD location (94, 62) without colliding with R10-R13 "
            "and K2. Where should the sockets go?"
        ),
        context={
            "board_size_mm": [160, 100],
            "current_u1_center_mm": [94, 62],
            "current_u1_bbox_mm": [48.05, 43.22],
            "devkit_bbox_mm": [55.88, 27.94],
            "obstructing_refs": ["R10", "R11", "R12", "R13", "K2"],
            "signal_targets": {
                "DWM_IRQ_3V3": {"target": "U4.3", "pos_mm": [121.16, 40.65]},
                "DWM_EXT_TX_3V3": {"target": "U5.3", "pos_mm": [127.16, 40.65]},
                "SPI_CS_3V3_MCU": {"target": "R10.1", "pos_mm": [133.17, 61.74]},
                "SPI_MOSI_3V3_MCU": {"target": "R11.1", "pos_mm": [131.74, 82.78]},
                "SPI_CLK_3V3_MCU": {"target": "R12.1", "pos_mm": [114.98, 87.48]},
                "SPI_MISO_3V3_MCU": {"target": "R13.1", "pos_mm": [96.70, 89.53]},
            },
        },
        suggested_choices=[
            {
                "id": "A",
                "label": "Place at top-left (40,30), pins horizontal",
                "consequence": "Frees U1 area; longer SPI routes (~50mm avg)",
            },
            {
                "id": "B",
                "label": "Place at top-right (120,30), pins horizontal",
                "consequence": "Shorter SPI routes (~25mm); conflicts with U4/U5",
            },
            {
                "id": "C",
                "label": "Expand board to 175×100, place at (167,50)",
                "consequence": "Breaks 160×100 enclosure fit; clean routing",
            },
            {
                "id": "D",
                "label": "Keep SMD WROOM (skip DevKit conversion)",
                "consequence": "Production ZIP already valid; no rework",
            },
        ],
    )
    print(json.dumps(demo, indent=2, ensure_ascii=False))
