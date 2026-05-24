from __future__ import annotations

from engine.omnicircuit.models import (
    AnalysisResult,
    DesignArtifact,
    ProjectInputs,
    ValidationCheck,
    utc_now_iso,
)


PASS = "pass"
WARN = "warning"
BLOCKED = "blocked"


def evaluate_uwb_anchor(inputs: ProjectInputs) -> AnalysisResult:
    text = f"{inputs.schematic_text}\n{inputs.pcb_notes_text}".lower()
    part_numbers = {item.part_number.lower() for item in inputs.bom_items}
    references = {item.reference.lower() for item in inputs.bom_items}
    checks = [
        _contains_all(
            "RF",
            "50 ohm controlled RF trace from DWM3000 pin 23 to SMA",
            text,
            ["pin 23", "50 ohm", "0.35mm", "3mm", "no vias", "continuous ground plane"],
            "Preserve the specified microstrip geometry and keep the RF path free of vias, probes, and components.",
        ),
        _contains_all(
            "RF",
            "Dense via stitching around SMA and RF section",
            text,
            ["via stitching", "sma", "rf section"],
            "Add explicit via fence coordinates during KiCad/PCBai placement export.",
        ),
        _contains_all(
            "Power",
            "Three-stage isolated power architecture",
            text,
            ["hlk-5m05", "tps54331", "tps780180", "100-240"],
            "Keep AC/DC isolation, 3.3V buck, and 1.8V LDO as separate validated power stages.",
        ),
        _contains_all(
            "Safety",
            "8mm AC isolation and high-voltage warning",
            text,
            ["8mm", "isolation", "danger high voltage"],
            "Emit board keepout, silkscreen warning, and fabrication notes in the PCB exporter.",
        ),
        _bom_has(
            "Protection",
            "ESD/EMI protection parts present",
            part_numbers,
            ["0451.500mrl", "mov-14d471k", "smbj5.0a", "blm21pg221sn1d"],
            "Keep fuse, MOV, TVS, and ferrite beads near entry and rail transition points.",
        ),
        _bom_has(
            "Level Shifting",
            "Required SPI and RTLS level shifters present",
            part_numbers,
            ["txb0104rut", "sn74lvc1t45dck"],
            "Constrain TXB0104 within 15mm and SN74LVC1T45 devices within 10mm of DWM3000 pins.",
        ),
        _contains_all(
            "Signal Integrity",
            "SPI length matching and series resistors",
            text,
            ["+/-2mm", "100 ohm", "r10-r13"],
            "During routing, constrain SPI length skew to 2mm and lock series resistors near ESP32 pins.",
        ),
        _contains_all(
            "RTLS",
            "Critical RTLS traces shorter than 30mm",
            text,
            ["ext_tx", "ext_rx", "irq", "shorter than 30mm"],
            "Place RTLS translators and pull/series resistors close to the DWM3000 edge.",
        ),
        _bom_has(
            "Expansion",
            "GPIO, I2C, UART, and power headers included",
            references,
            ["j6-j13", "j14", "j15", "j16"],
            "Keep expansion headers at board edges with readable silkscreen and ground return pins.",
        ),
        _contains_all(
            "Testability",
            "All 18 named test points documented",
            text,
            [f"tp{i}" for i in range(1, 19)],
            "Exporter should place TP1-TP18 near accessible board edges and include them in CPL exclusions.",
        ),
    ]

    artifacts = [
        DesignArtifact(
            "AI Design Report",
            "outputs/uwb_anchor/AI_DESIGN_REPORT.md",
            "generated",
            "Readable summary of design choices, checks, and next KiCad/PCBai actions.",
        ),
        DesignArtifact(
            "Validation Report",
            "outputs/uwb_anchor/VALIDATION_REPORT.md",
            "generated",
            "DRC/ERC/DFM/DFA-oriented checklist for the UWB anchor constraints.",
        ),
        DesignArtifact(
            "Manufacturing Handoff",
            "outputs/uwb_anchor/manufacturing/",
            "scaffolded",
            "PCBWay-compatible package structure with BOM and CPL placeholders.",
        ),
        DesignArtifact(
            "Dashboard Asset",
            "assets/generated/uwb_anchor_analysis.json",
            "generated",
            "JSON consumed by the Flutter dashboard.",
        ),
    ]
    overall = PASS if all(check.status == PASS for check in checks) else WARN
    return AnalysisResult(
        project_id="uwb_anchor",
        project_name="ESP32-S3 + DWM3000 UWB Anchor",
        generated_at=utc_now_iso(),
        overall_status=overall,
        checks=checks,
        artifacts=artifacts,
    )


def _contains_all(
    category: str,
    requirement: str,
    text: str,
    tokens: list[str],
    recommendation: str,
) -> ValidationCheck:
    missing = [token for token in tokens if token.lower() not in text]
    if not missing:
        return ValidationCheck(category, requirement, PASS, "All required source markers found.", recommendation)
    evidence = f"Missing source marker(s): {', '.join(missing)}"
    return ValidationCheck(category, requirement, WARN, evidence, recommendation)


def _bom_has(
    category: str,
    requirement: str,
    values: set[str],
    expected: list[str],
    recommendation: str,
) -> ValidationCheck:
    missing = [value for value in expected if value.lower() not in values]
    if not missing:
        return ValidationCheck(category, requirement, PASS, "All required BOM entries found.", recommendation)
    evidence = f"Missing BOM value(s): {', '.join(missing)}"
    return ValidationCheck(category, requirement, WARN, evidence, recommendation)
