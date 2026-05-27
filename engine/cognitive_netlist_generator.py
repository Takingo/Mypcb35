from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AI_NETLIST_VERSION = "AI_Netlist_v1"


class KiCadAINetlistInsufficient(RuntimeError):
    """Gerçek AI çağrısı boş/yetersiz netlist döndürdüğünde fırlatılır."""


@dataclass(frozen=True)
class Component:
    ref: str
    type: str
    value: str
    manufacturer: str
    part_number: str
    footprint: str
    reason: str
    constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NetConnection:
    net: str
    pins: list[str]
    net_class: str
    reason: str


@dataclass(frozen=True)
class DesignRule:
    id: str
    severity: str
    description: str
    applies_to: list[str]


@dataclass(frozen=True)
class ReasoningStep:
    level: str
    message: str
    outcome: str


@dataclass(frozen=True)
class AiNetlist:
    schema: str
    project_name: str
    generated_at: str
    source_prompt: str
    assumptions: list[str]
    components: list[Component]
    nets: list[NetConnection]
    rules: list[DesignRule]
    reasoning_log: list[ReasoningStep]
    erc_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SYSTEM_PROMPT = """You are OmniCircuit AI, a generative EDA lead engineer.
Return ONLY valid JSON matching AI_Netlist_v1 schema. Infer missing glue logic, protection,
power rails, level translation, relay isolation, and DRC/ERC constraints.

CRITICAL ENGINEERING CONSTRAINT:
Qorvo DWM3000 UWB modülünün pin aralığı (pitch) standart kütüphanelerdeki gibi 1.27mm DEĞİL, mutlak surette 1.0mm olarak hesaplanmalı ve KiCad'e bu şekilde iletilmelidir! (Add this to the constraints array for DWM3000).

JSON SCHEMA TO FOLLOW EXACTLY:
{
  "schema": "AI_Netlist_v1",
  "project_name": "Project Name",
  "assumptions": ["List of assumed engineering constraints"],
  "components": [
    {
      "ref": "U1",
      "type": "mcu",
      "value": "ESP32-S3 module",
      "manufacturer": "Espressif",
      "part_number": "ESP32-S3-WROOM-1",
      "footprint": "SMD",
      "reason": "Main controller",
      "constraints": ["Constraint 1"]
    }
  ],
  "nets": [
    {
      "net": "+3V3",
      "pins": ["U1.3V3", "R1.1"],
      "net_class": "power",
      "reason": "Main 3.3V supply"
    }
  ],
  "rules": [
    {
      "id": "AC_CLEARANCE",
      "severity": "error",
      "description": "Maintain 8mm clearance",
      "applies_to": ["ALL"]
    }
  ],
  "reasoning_log": [
    {
      "level": "info",
      "message": "Added level shifters",
      "outcome": "accepted"
    }
  ],
  "erc_summary": {
    "status": "pass",
    "checks": ["Checked power rails"]
  }
}
"""


USER_PROMPT_TEMPLATE = """Analyze this hardware request and synthesize an industrial PCB netlist.

User request:
{user_request}

Required cognitive tasks:
- Derive power tree and protection.
- Detect voltage-domain mismatches.
- Add required level shifters, pull-ups, series resistors, optocouplers, and relay drivers.
- Emit components, nets, reasoning_log, and DRC/ERC rules.

Return JSON only with schema AI_Netlist_v1."""


class CognitiveNetlistGenerator:
    """Phase 1 deterministic generator with an LLM prompt boundary.

    The deterministic rule engine is the source of truth for safety-critical
    glue logic. A future LLM adapter can propose candidates, but final output
    should still pass these explicit checks before layout export.

    IMPORTANT: synthesize_real() does NOT catch provider errors.
    run_ai_synthesis.py catches them and reports failure honestly to the UI.
    The UI then decides whether to use its own deterministic fallback.
    """

    def synthesize_real(self, user_request: str) -> AiNetlist:
        """Call the configured AI provider. RAISES on any failure — never silently falls back.

        This ensures run_ai_synthesis.py can honestly report success/failure
        to the Flutter UI without pretending real AI ran when fallback was used.
        """
        try:
            from engine.ollama_client import OllamaClient
        except ImportError:
            from ollama_client import OllamaClient  # type: ignore

        client = OllamaClient()
        provider = client.provider
        model = client.model

        print(f"[AI] {provider.upper()} / {model} ile baglanti kuruluyor...", flush=True)

        # Errors propagate — no internal try/except, no silent fallback
        result = client.generate_json(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            user_prompt=USER_PROMPT_TEMPLATE.format(user_request=user_request),
        )

        components = [Component(**c) for c in result.get("components", [])]
        nets = [NetConnection(**n) for n in result.get("nets", [])]
        rules = [DesignRule(**r) for r in result.get("rules", [])]
        reasoning = [ReasoningStep(**r) for r in result.get("reasoning_log", [])]

        # Boş/yetersiz AI çıktısını başarı sayma — kaynaksız netlist üretim kapısını
        # bloklar. Yetersizse dürüstçe hata fırlat; çağıran deterministik motora geçer.
        if len(components) < 3 or len(nets) < 2:
            raise KiCadAINetlistInsufficient(
                f"AI yetersiz netlist dondurdu: {len(components)} komponent, {len(nets)} net "
                f"(en az 3 komponent ve 2 net gerekli)."
            )

        print(f"[AI] {provider.upper()} API basariyla netlist uretti.", flush=True)
        return AiNetlist(
            schema=result.get("schema", "AI_Netlist_v1"),
            project_name=result.get("project_name", "AI_Generated_Project"),
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            source_prompt=user_request,
            assumptions=result.get("assumptions", []),
            components=components,
            nets=nets,
            rules=rules,
            reasoning_log=reasoning,
            erc_summary=result.get("erc_summary", {"status": "review_required", "checks": []}),
        )

    def synthesize(self, user_request: str) -> AiNetlist:
        """Legacy wrapper: tries real AI, silently falls back on error.

        Use synthesize_real() from run_ai_synthesis.py to get honest
        success/failure reporting to the Flutter UI.
        """
        try:
            return self.synthesize_real(user_request)
        except Exception as e:
            print(f"[FALLBACK] Gercek AI basarisiz: {e}. Deterministik motora geciliyor...", flush=True)
            return self._synthesize_fallback(user_request)

    def _synthesize_fallback(self, user_request: str) -> AiNetlist:
        normalized = user_request.lower()
        components: list[Component] = []
        nets: list[NetConnection] = []
        rules: list[DesignRule] = []
        reasoning: list[ReasoningStep] = []
        assumptions = [
            "AC mains input is isolated before low-voltage logic.",
            "ESP32-S3 logic domain is 3.3V.",
            "DWM3000 logic and RF module domain is 1.8V.",
            "Relay coils are 5V and must not be driven directly from MCU pins.",
        ]

        self._add_core_components(normalized, components, reasoning)
        self._add_power_tree(normalized, components, nets, rules, reasoning)
        self._add_uwb_level_translation(normalized, components, nets, rules, reasoning)
        relay_count = self._relay_count(normalized)
        self._add_relay_isolation(relay_count, components, nets, rules, reasoning)
        self._add_rf_rules(nets, rules, reasoning)
        self._add_erc_summary_rules(rules)

        erc_summary = {
            "status": "pass_with_engineering_review_required",
            "checks": [
                "Power rails inferred: 5V, 3V3, 1V8",
                "Voltage mismatch mitigation added for SPI and RTLS lines",
                "Relay isolation and low-side drivers added",
                "AC clearance and RF impedance rules emitted",
            ],
        }
        return AiNetlist(
            schema=AI_NETLIST_VERSION,
            project_name="ESP32-S3 DWM3000 UWB Anchor with Relay Outputs",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            source_prompt=user_request,
            assumptions=assumptions,
            components=components,
            nets=nets,
            rules=rules,
            reasoning_log=reasoning,
            erc_summary=erc_summary,
        )

    def llm_prompt(self, user_request: str) -> dict[str, str]:
        return {
            "system": SYSTEM_PROMPT,
            "user": USER_PROMPT_TEMPLATE.format(user_request=user_request),
        }

    def _add_core_components(
        self,
        normalized: str,
        components: list[Component],
        reasoning: list[ReasoningStep],
    ) -> None:
        if "esp32" in normalized:
            components.append(
                Component(
                    "U1",
                    "mcu",
                    "ESP32-S3 module",
                    "Espressif",
                    "ESP32-S3-WROOM-1",
                    "SMD module",
                    "User requested ESP32-S3 host controller.",
                    ["3V3 logic", "place away from AC isolation slot"],
                )
            )
            reasoning.append(ReasoningStep("info", "ESP32-S3 detected as 3.3V host MCU.", "accepted"))

        if "dwm3000" in normalized or "uwb" in normalized:
            components.append(
                Component(
                    "U2",
                    "uwb_module",
                    "DWM3000",
                    "Qorvo",
                    "DWM3000",
                    "SMD module",
                    "User requested UWB positioning radio.",
                    ["1V8 logic", "RF launch requires 50 ohm net class"],
                )
            )
            reasoning.append(ReasoningStep("info", "DWM3000 detected as 1.8V UWB domain.", "accepted"))

    def _add_power_tree(
        self,
        normalized: str,
        components: list[Component],
        nets: list[NetConnection],
        rules: list[DesignRule],
        reasoning: list[ReasoningStep],
    ) -> None:
        if "220v" not in normalized and "ac" not in normalized:
            return

        components.extend(
            [
                Component("F1", "fuse", "500mA", "Littelfuse", "0451.500MRL", "Fuse", "Protect AC input."),
                Component("MOV1", "varistor", "MOV 471VAC", "Bourns", "MOV-14D471K", "Disc", "Clamp AC surge."),
                Component("U6", "ac_dc", "5V isolated", "Hi-Link", "HLK-5M05", "Module", "Convert AC mains to isolated 5V."),
                Component("U7", "buck", "3.3V", "Texas Instruments", "TPS54331DR", "SOIC-8", "Generate ESP32 3.3V rail."),
                Component("U8", "ldo", "1.8V low-noise", "Texas Instruments", "TPS7A2018PDBVR", "SOT-23-5", "Generate DWM3000 1.8V rail with higher current margin than TPS780."),
            ]
        )
        nets.extend(
            [
                NetConnection("AC_L_PROTECTED", ["J1.L", "F1.1", "MOV1.1", "U6.AC_L"], "mains", "Fused AC live input."),
                NetConnection("AC_N", ["J1.N", "MOV1.2", "U6.AC_N"], "mains", "AC neutral reference."),
                NetConnection("+5V_ISO", ["U6.+VO", "U7.VIN", "K1.COIL+", "K2.COIL+"], "power_5v", "Isolated 5V rail for relays and buck input."),
                NetConnection("+3V3", ["U7.SW_OUT", "U1.3V3", "U3.VCCA", "U4.VCCA", "U5.VCCA"], "power_3v3", "ESP32 and high side level shifter rail."),
                NetConnection("+1V8", ["U8.OUT", "U2.VDDIO", "U3.VCCB", "U4.VCCB", "U5.VCCB"], "power_1v8", "DWM3000 and low side level shifter rail."),
                NetConnection("GND", ["U6.-VO", "U7.GND", "U8.GND", "U1.GND", "U2.GND", "U3.GND", "U3.GND2", "U4.GND", "U4.DIR", "U5.GND", "U5.DIR"], "ground", "Low-voltage ground return."),
            ]
        )
        rules.append(
            DesignRule(
                "AC_CLEARANCE_8MM",
                "error",
                "Maintain at least 8mm clearance and isolation slot between AC primary and low-voltage domains.",
                ["J1", "F1", "MOV1", "U6"],
            )
        )
        reasoning.append(
            ReasoningStep(
                "warning",
                "220V AC detected. Added fuse, MOV, isolated AC/DC, 3.3V buck, and 1.8V LDO power chain.",
                "successful",
            )
        )

    def _add_uwb_level_translation(
        self,
        normalized: str,
        components: list[Component],
        nets: list[NetConnection],
        rules: list[DesignRule],
        reasoning: list[ReasoningStep],
    ) -> None:
        if "esp32" not in normalized or ("dwm3000" not in normalized and "uwb" not in normalized):
            return

        components.extend(
            [
                Component("U3", "level_shifter", "4-bit bidirectional", "Texas Instruments", "TXB0104RUT", "QFN", "Translate SPI between 3.3V ESP32 and 1.8V DWM3000."),
                Component("U4", "level_shifter", "single-bit dual-supply", "Texas Instruments", "SN74LVC1T45DCK", "SC70", "Translate DWM3000 IRQ."),
                Component("U5", "level_shifter", "single-bit dual-supply", "Texas Instruments", "SN74LVC1T45DCK", "SC70", "Translate DWM3000 EXT_TX."),
                Component("R10", "resistor", "100R", "Yageo", "RC0603FR-07100RL", "0603", "SPI CS source termination close to ESP32."),
                Component("R11", "resistor", "100R", "Yageo", "RC0603FR-07100RL", "0603", "SPI MOSI source termination close to ESP32."),
                Component("R12", "resistor", "100R", "Yageo", "RC0603FR-07100RL", "0603", "SPI CLK source termination close to ESP32."),
                Component("R13", "resistor", "100R", "Yageo", "RC0603FR-07100RL", "0603", "SPI MISO source termination close to ESP32."),
            ]
        )
        nets.extend(
            [
                NetConnection("SPI_CS_3V3", ["U1.GPIO10", "R10.1", "R10.2", "U3.A1"], "spi_3v3", "ESP32 SPI chip select through source resistor."),
                NetConnection("SPI_MOSI_3V3", ["U1.GPIO11", "R11.1", "R11.2", "U3.A2"], "spi_3v3", "ESP32 SPI MOSI through source resistor."),
                NetConnection("SPI_CLK_3V3", ["U1.GPIO12", "R12.1", "R12.2", "U3.A3"], "spi_3v3", "ESP32 SPI clock through source resistor."),
                NetConnection("SPI_MISO_3V3", ["U1.GPIO13", "R13.1", "R13.2", "U3.A4"], "spi_3v3", "ESP32 SPI MISO through source resistor."),
                NetConnection("SPI_CS_1V8", ["U3.B1", "U2.SPI_CS"], "spi_1v8", "Translated DWM3000 SPI chip select."),
                NetConnection("SPI_MOSI_1V8", ["U3.B2", "U2.SPI_MOSI"], "spi_1v8", "Translated DWM3000 SPI MOSI."),
                NetConnection("SPI_CLK_1V8", ["U3.B3", "U2.SPI_CLK"], "spi_1v8", "Translated DWM3000 SPI clock."),
                NetConnection("SPI_MISO_1V8", ["U3.B4", "U2.SPI_MISO"], "spi_1v8", "Translated DWM3000 SPI MISO."),
                NetConnection("DWM_IRQ_3V3", ["U4.A", "U1.GPIO14"], "rtls_3v3", "IRQ translated to ESP32 domain."),
                NetConnection("DWM_IRQ_1V8", ["U4.B", "U2.IRQ"], "rtls_1v8", "IRQ source from DWM3000 domain."),
                NetConnection("DWM_EXT_TX_3V3", ["U5.A", "U1.GPIO15"], "rtls_3v3", "EXT_TX translated to ESP32 domain."),
                NetConnection("DWM_EXT_TX_1V8", ["U5.B", "U2.EXT_TX"], "rtls_1v8", "EXT_TX source from DWM3000 domain."),
            ]
        )
        rules.extend(
            [
                DesignRule("SPI_LENGTH_MATCH_2MM", "error", "SPI traces must be length matched within +/-2mm.", ["SPI_*"]),
                DesignRule("TXB0104_DISTANCE_15MM", "error", "Place TXB0104 within 15mm of DWM3000.", ["U2", "U3"]),
                DesignRule("RTLS_TRANSLATOR_DISTANCE_10MM", "error", "Place IRQ and EXT_TX translators within 10mm of DWM3000 pins.", ["U2", "U4", "U5"]),
            ]
        )
        reasoning.append(
            ReasoningStep(
                "warning",
                "ESP32 3.3V and DWM3000 1.8V mismatch detected. Added TXB0104 for SPI and SN74LVC1T45 translators for RTLS pins.",
                "successful",
            )
        )

    def _add_relay_isolation(
        self,
        relay_count: int,
        components: list[Component],
        nets: list[NetConnection],
        rules: list[DesignRule],
        reasoning: list[ReasoningStep],
    ) -> None:
        if relay_count == 0:
            return

        for index in range(1, relay_count + 1):
            components.extend(
                [
                    Component(f"K{index}", "relay", "5V relay", "Omron", "G5Q-14-DC5", "Relay", "User requested isolated relay output."),
                    Component(f"OK{index}", "optocoupler", "PC817", "Sharp", "PC817", "DIP/SMD-4", "Protect ESP32 GPIO from relay driver domain."),
                    Component(f"Q{index}", "n_mosfet", "2N7002", "Onsemi", "2N7002", "SOT-23", "Low-side relay coil driver."),
                    Component(f"D{index}", "flyback_diode", "SS14", "Vishay", "SS14", "SMA", "Clamp relay coil flyback."),
                    Component(f"R{30 + index}", "resistor", "330R", "Yageo", "RC0603FR-07330RL", "0603", "Optocoupler LED current limit."),
                    Component(f"R{40 + index}", "resistor", "100K", "Yageo", "RC0603FR-07100KL", "0603", "MOSFET gate pulldown."),
                ]
            )
            nets.extend(
                [
                    NetConnection(f"RELAY{index}_CTRL", [f"U1.GPIO{20 + index}", f"R{30 + index}.1", f"OK{index}.A"], "gpio", "ESP32 relay command through optocoupler LED."),
                    NetConnection(f"RELAY{index}_GATE", [f"OK{index}.C", f"Q{index}.G", f"R{40 + index}.1"], "relay_drive", "Isolated gate drive for MOSFET."),
                    NetConnection(f"RELAY{index}_COIL_LOW", [f"K{index}.COIL-", f"Q{index}.D", f"D{index}.A"], "relay_drive", "Relay coil low side switched by MOSFET."),
                ]
            )

        rules.append(
            DesignRule(
                "RELAY_NO_DIRECT_GPIO_DRIVE",
                "error",
                "Relay coils must not connect directly to ESP32 GPIO. Use optocoupler, MOSFET, and flyback diode.",
                [f"K{i}" for i in range(1, relay_count + 1)],
            )
        )
        reasoning.append(
            ReasoningStep(
                "warning",
                f"{relay_count} relay output(s) detected. Added PC817 isolation, 2N7002 low-side drivers, flyback diodes, and gate pulldowns.",
                "successful",
            )
        )

    def _add_rf_rules(
        self,
        nets: list[NetConnection],
        rules: list[DesignRule],
        reasoning: list[ReasoningStep],
    ) -> None:
        nets.append(NetConnection("UWB_RF_50R", ["U2.RF_PIN23", "J2.CENTER"], "rf_50r", "DWM3000 RF output to SMA antenna connector."))
        rules.extend(
            [
                DesignRule("RF_50R_WIDTH_035MM", "error", "RF trace must be 50 ohm controlled impedance with 0.35mm width on specified FR4 stackup.", ["UWB_RF_50R"]),
                DesignRule("RF_NO_VIAS_OR_TESTPOINTS", "error", "No vias, test points, or components are allowed on the RF trace.", ["UWB_RF_50R"]),
                DesignRule("RF_KEEP_OUT_3MM", "error", "Maintain 3mm RF keepout around antenna trace.", ["UWB_RF_50R"]),
            ]
        )
        reasoning.append(ReasoningStep("info", "Added RF net class and keepout constraints for DWM3000 pin 23 to SMA.", "successful"))

    def _add_erc_summary_rules(self, rules: list[DesignRule]) -> None:
        rules.extend(
            [
                DesignRule("POWER_RAIL_SEQUENCE", "warning", "Validate 5V before 3V3 before 1V8 startup behavior.", ["+5V_ISO", "+3V3", "+1V8"]),
                DesignRule("HUMAN_REVIEW_REQUIRED", "warning", "Human engineer must review AC safety, RF impedance, relay isolation, and final DRC/ERC before fabrication.", ["ALL"]),
            ]
        )

    def _relay_count(self, normalized: str) -> int:
        count_match = re.search(r"(\d+)\s*(adet\s*)?(g5q|role|röle|relay)", normalized)
        if count_match:
            return int(count_match.group(1))
        return 1 if any(token in normalized for token in ("g5q", "role", "röle", "relay")) else 0


def write_netlist(project_root: Path, user_request: str) -> Path:
    generator = CognitiveNetlistGenerator()
    netlist = generator.synthesize(user_request)
    output_dir = project_root / "outputs" / "phase1"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "AI_NETLIST_V1.example.json"
    output_path.write_text(json.dumps(netlist.to_dict(), indent=2), encoding="utf-8")
    prompt_path = output_dir / "LLM_PROMPT_TEMPLATE.json"
    prompt_path.write_text(json.dumps(generator.llm_prompt(user_request), indent=2), encoding="utf-8")
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an AI_Netlist_v1 from a hardware request.")
    parser.add_argument(
        "--request",
        default="Bana ESP32-S3 3.3V, DWM3000 UWB modulu 1.8V, 220V AC giris ve 2 adet G5Q-14-DC5 5V role iceren bir konumlandirma cihazi tasarla.",
    )
    parser.add_argument("--project-root", default=".")
    args = parser.parse_args()
    output_path = write_netlist(Path(args.project_root).resolve(), args.request)
    print(f"Generated {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
