"""Run Freerouting on the current PCB to auto-route all unrouted signals.

Pipeline:
  1. Load PCB via pcbnew
  2. Export to Specctra DSN (pcbnew.ExportSpecctraDSN)
  3. Call Freerouting CLI:  java -jar freerouting.jar -de in.dsn -do out.ses
  4. Import the resulting SES file back into the board (pcbnew.ImportSpecctraSES)
  5. Save the board

This is the missing piece that lets the full pipeline reach DRC=0 without
human intervention. Freerouting is the community-standard open-source
auto-router for the KiCad ecosystem.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, r"C:\Program Files\KiCad\10.0\bin")
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import pcbnew  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PCB = ROOT / "outputs" / "kicad" / "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs" / "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
PCB = Path(os.environ.get("PCB_FILE", sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_PCB))).resolve()
# DÜZELTME: freerouting-2.2.4 Java 25 gerektirir, sistemde Java 11 var.
# Java 11 ile uyumlu freerouting-1.9.0 kullanılıyor.
FREEROUTING_JAR = Path(os.environ.get("FREEROUTING_JAR", str(ROOT / "tools" / "freerouting-2.2.4.jar"))).resolve()
JAVA_EXE = Path(os.environ.get("JAVA_EXE", str(ROOT / "tools" / "java" / "temurin25" / "jdk-25.0.3+9" / "bin" / "java.exe")))
DSN = PCB.with_suffix(".dsn")
SES = PCB.with_suffix(".ses")

MAX_PASSES = int(os.environ.get("FR_MAX_PASSES", "1"))
THREADS = int(os.environ.get("FR_THREADS", "1"))
TIMEOUT_S = int(os.environ.get("FR_TIMEOUT_S", "600"))


def export_dsn(board: object) -> bool:
    print(f"[FR] exporting DSN: {DSN.name}", flush=True)
    try:
        pcbnew.ExportSpecctraDSN(board, str(DSN))
    except TypeError:
        # Some KiCad builds expose ExportSpecctraDSN(filename) only (uses currently-loaded board)
        pcbnew.ExportSpecctraDSN(str(DSN))
    if not DSN.exists() or DSN.stat().st_size < 100:
        print(f"[FR] FAIL: DSN not produced (size={DSN.stat().st_size if DSN.exists() else 0})", flush=True)
        return False
    print(f"[FR] DSN written: {DSN.stat().st_size:,} bytes", flush=True)
    reserve_inner_layers_for_planes()
    return True


def reserve_inner_layers_for_planes() -> None:
    if os.environ.get("FR_ROUTE_INNER_LAYERS", "0") == "1":
        return
    text = DSN.read_text(encoding="utf-8", errors="ignore")
    updated = text
    for layer_name in ("In1.Cu", "In2.Cu"):
        updated = re.sub(
            rf"(\(layer\s+{re.escape(layer_name)}\s*\n\s*)\(type\s+signal\)",
            rf"\1(type power)",
            updated,
            count=1,
        )
    if updated != text:
        DSN.write_text(updated, encoding="utf-8")
        print("[FR] Inner copper layers reserved for planes; routing limited to F.Cu/B.Cu.", flush=True)


def run_freerouting() -> bool:
    if not FREEROUTING_JAR.exists():
        print(f"[FR] FAIL: jar missing at {FREEROUTING_JAR}", flush=True)
        return False
    # Remove any previous SES so we can detect a fresh write
    if SES.exists():
        SES.unlink()
    cmd = [
        str(JAVA_EXE),
        "-jar", str(FREEROUTING_JAR),
        "--gui.enabled=false",
        "-de", str(DSN),
        "-do", str(SES),
        "-mp", str(MAX_PASSES),
        "-mt", str(THREADS),
    ]
    print(f"[FR] running: {' '.join(cmd)}", flush=True)
    t0 = time.time()
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        print(f"[FR] FAIL: timeout after {TIMEOUT_S}s", flush=True)
        return False
    dt = time.time() - t0
    # Freerouting writes progress to stderr/stdout; show last few lines
    tail = "\n".join((r.stderr or r.stdout or "").splitlines()[-8:])
    print(f"[FR] finished in {dt:.1f}s, exit={r.returncode}", flush=True)
    if tail:
        print(f"[FR] tail:\n{tail}", flush=True)
    if not SES.exists() or SES.stat().st_size < 100:
        print(f"[FR] FAIL: SES not produced", flush=True)
        return False
    print(f"[FR] SES written: {SES.stat().st_size:,} bytes", flush=True)
    return True


def import_ses(board: object) -> bool:
    print(f"[FR] importing SES into board...", flush=True)
    try:
        pcbnew.ImportSpecctraSES(board, str(SES))
    except TypeError:
        pcbnew.ImportSpecctraSES(str(SES))
    return True


def main() -> int:
    if not PCB.exists():
        print(f"[FR] FAIL: PCB not found at {PCB}", flush=True)
        return 1

    board = pcbnew.LoadBoard(str(PCB))
    if board is None:
        print(f"[FR] FAIL: could not load PCB", flush=True)
        return 1

    # Snapshot track count before
    tracks_before = len(list(board.GetTracks()))
    print(f"[FR] before: {tracks_before} tracks", flush=True)

    if os.environ.get("FR_RIPUP_LONG_TRACKS", "0") == "1":
        # Optional engineer override. Default is conservative: preserve any
        # intentional KiCad pre-route such as RF stubs, power trunks, or fanout.
        to_remove = []
        for track in board.GetTracks():
            if type(track) == pcbnew.PCB_TRACK:
                dx = track.GetStart().x - track.GetEnd().x
                dy = track.GetStart().y - track.GetEnd().y
                length_nm = (dx * dx + dy * dy) ** 0.5
                if length_nm > 3000000:
                    to_remove.append(track)

        for track in to_remove:
            board.Remove(track)

        print(f"[FR] Ripped up {len(to_remove)} long tracks before routing.", flush=True)

    if not export_dsn(board):
        return 2
    if not run_freerouting():
        return 3
    if not import_ses(board):
        return 4

    if not pcbnew.SaveBoard(str(PCB), board):
        print("[FR] FAIL: SaveBoard failed", flush=True)
        return 5

    # Reload to verify
    verify = pcbnew.LoadBoard(str(PCB))
    if verify is None:
        print("[FR] WARN: post-save reload returned None (SWIG ownership quirk)", flush=True)
        tracks_after = -1
    else:
        tracks_after = len(list(verify.GetTracks()))
    print(f"[FR] after: {tracks_after} tracks  (delta: {tracks_after - tracks_before:+d})", flush=True)
    print(f"[FR] OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
