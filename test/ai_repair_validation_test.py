"""AI tamir dongusu dogrulama gate testi (real-not-mock).

LLM ne dondururse dondursun, deterministik sema/guvenlik gate'inin iyi/kotu/
guvenlik-kritik onerileri dogru ayirdigini ve candidate'in canli netlist'i
bozmadan uygulandigini kanitlar.

Calistirma:
    & "C:\\Program Files\\KiCad\\10.0\\bin\\python.exe" test\\ai_repair_validation_test.py
    veya herhangi bir Python 3.10+ ile (pcbnew gerekmez).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.ai_repair_service import AiRepairService  # noqa: E402


def _netlist() -> dict:
    return {
        "schema": "AI_Netlist_v1",
        "project_name": "test",
        "components": [
            {"ref": "U1", "type": "mcu", "value": "ESP32-S3", "manufacturer": "Espressif",
             "part_number": "ESP32-S3-WROOM-1", "footprint": "RF_Module:ESP32-S3-WROOM-1",
             "reason": "host", "constraints": []},
            {"ref": "C5", "type": "capacitor", "value": "100nF", "manufacturer": "Murata",
             "part_number": "GRM21BR71H104KA01L", "footprint": "Capacitor_SMD:C_0805_2012Metric",
             "reason": "decap", "constraints": []},
        ],
        "nets": [
            {"net": "+3V3", "pins": ["U1.3V3", "C5.1"], "net_class": "power", "reason": "rail"},
            {"net": "AC_L_PROTECTED", "pins": ["U1.GND"], "net_class": "mains", "reason": "ac"},
        ],
    }


def main() -> int:
    svc = AiRepairService(Path.cwd())
    nl = _netlist()

    ops = [
        # 1) gecerli decoupling net -> accepted
        {"op": "add_net", "target": "DECOUPLE_U1", "fields": {"pins": ["U1.GND", "C5.1"], "net_class": "power"},
         "reason": "missing decap return", "confidence": 0.85, "requires_user_evidence": False},
        # 2) guvenlik-kritik AC net -> needs_evidence
        {"op": "modify_net", "target": "AC_L_PROTECTED", "fields": {"add_pins": ["C5.2"]},
         "reason": "tie", "confidence": 0.95, "requires_user_evidence": False},
        # 3) dusuk confidence -> rejected
        {"op": "modify_component", "target": "U1", "fields": {"value": "X"},
         "reason": "guess", "confidence": 0.30, "requires_user_evidence": False},
        # 4) olmayan komponent -> rejected
        {"op": "remove_component", "target": "U999", "fields": {},
         "reason": "?", "confidence": 0.9, "requires_user_evidence": False},
        # 5) bilinmeyen komponente pin -> rejected
        {"op": "add_net", "target": "BADPIN", "fields": {"pins": ["U999.1"]},
         "reason": "?", "confidence": 0.9, "requires_user_evidence": False},
        # 6) gecerli MPN duzeltmesi -> accepted
        {"op": "modify_component", "target": "C5", "fields": {"part_number": "GRM188R71C104KA93D"},
         "reason": "BOM MPN align", "confidence": 0.9, "requires_user_evidence": False},
    ]

    res = svc.validate_proposals(nl, ops)
    failures = []

    def expect(name, cond):
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            failures.append(name)

    print("validate_proposals:")
    expect("2 accepted", len(res["accepted"]) == 2)
    expect("1 needs_evidence (AC safety net)", len(res["questions"]) == 1)
    expect("3 rejected", len(res["rejected"]) == 3)
    accepted_targets = {o["target"] for o in res["accepted"]}
    expect("DECOUPLE_U1 accepted", "DECOUPLE_U1" in accepted_targets)
    expect("C5 MPN accepted", "C5" in accepted_targets)
    expect("AC_L_PROTECTED flagged for evidence",
           any(q["operation"]["target"] == "AC_L_PROTECTED" for q in res["questions"]))

    print("apply_to_candidate:")
    cand = svc.apply_to_candidate(nl, res["accepted"])
    c5 = next(c for c in cand["components"] if c["ref"] == "C5")
    expect("C5 MPN updated in candidate", c5["part_number"] == "GRM188R71C104KA93D")
    expect("DECOUPLE_U1 net added in candidate",
           any(n["net"] == "DECOUPLE_U1" for n in cand["nets"]))
    # canli netlist DEGISMEMELI (deepcopy guvenligi)
    orig_c5 = next(c for c in nl["components"] if c["ref"] == "C5")
    expect("original netlist untouched (deepcopy)",
           orig_c5["part_number"] == "GRM21BR71H104KA01L"
           and not any(n["net"] == "DECOUPLE_U1" for n in nl["nets"]))

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} assertion(s)): {failures}")
        return 1
    print("RESULT: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
