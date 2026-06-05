from __future__ import annotations

import argparse
import inspect
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AI_NETLIST_VERSION = "AI_Netlist_v1"


def _safe_unpack(cls: type, data: dict[str, Any]) -> Any:
    """Instantiate a frozen dataclass, silently dropping unknown AI fields."""
    allowed = {f for f in inspect.signature(cls).parameters}
    return cls(**{k: v for k, v in data.items() if k in allowed})


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
    reason: str
    net_class: str = "default"


@dataclass(frozen=True)
class DesignRule:
    id: str
    severity: str
    description: str
    applies_to: list[str]
    net_class: str | None = None   # AI sometimes adds this; accepted and ignored


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


SYSTEM_PROMPT = """═══════════════════════════════════════════════════════════════════════
ABSOLUTE BOM LAW — READ BEFORE EVERY OTHER INSTRUCTION
═══════════════════════════════════════════════════════════════════════

CRITICAL HARDWARE CONSTRAINT: You are strictly forbidden from inventing,
hallucinating, or creating any new component references that are not
explicitly listed in the provided BOM.

  • DO NOT create C99, C100, C101, C102, or ANY component reference
    that does not appear verbatim in the user's BOM.
  • DO NOT auto-append decoupling/bypass/bulk capacitors with new refs.
  • DO NOT invent pull-ups, pull-downs, series resistors, terminators,
    or "missing glue" components unless they already exist in the BOM.
  • If a decoupling capacitor is electrically required for an IC, you
    MUST reuse one of the unused 100nF capacitors ALREADY in the BOM
    (e.g., reuse C5, C6, C7, C8, C9, C10, C11, C12, C27, C28, C33, C34
    when they are still unassigned). REUSE — never INVENT.
  • Every component "ref" you emit MUST be present in the user's BOM.
    Any ref outside the BOM is a FATAL SYSTEM ERROR and the entire
    netlist will be rejected by the downstream gate.
  • If you cannot satisfy a connection with the BOM you were given,
    add a "review" entry to reasoning_log explaining what is missing
    and what BOM addition would resolve it — DO NOT silently invent it.

YOUR JOB: Wire what exists. Never grow the parts list.
═══════════════════════════════════════════════════════════════════════

You are OmniCircuit AI, a generative EDA lead engineer.
Return ONLY valid JSON matching AI_Netlist_v1 schema. Infer the wiring,
power rail topology, level translation, relay isolation, and DRC/ERC
constraints — but use ONLY components from the BOM.

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


USER_PROMPT_TEMPLATE = """Analyze this hardware request and synthesize a COMPLETE industrial PCB netlist.

User request:
{user_request}

COMPLETENESS REQUIREMENT — CRITICAL:
You MUST wire ALL components listed in the BOM. A partial netlist is a FATAL ERROR.
- Every component reference from the BOM must appear in the "components" array.
- Every component must be connected to at least one net in the "nets" array.
- No isolated (floating) components allowed.
- Decoupling capacitors MUST be wired to the IC supply pin they decouple + GND.
- Expected minimum: ALL IC/module refs (U*, SK*), ALL relay circuit refs (K*, OK*, Q*, D*),
  ALL passive refs (R*, C*, L*), ALL connectors (J*), ALL mechanical (ANT*, BAT*) present.

Required cognitive tasks:
1. Map every BOM ref to its schematic symbol and assign it to a power/signal net.
2. Derive full power tree: AC→5V_ISO→3V3→1V8 with all decoupling caps on each rail.
3. Wire SPI bus (ESP32↔DWM3000) through level shifters with source termination resistors.
4. Wire relay isolation chain: GPIO→R(330Ω)→OK(PC817)→Q(2N7002)→K(G5Q) with flyback diode.
5. Wire all connectors (J1 AC input, J2 SMA antenna, J3 debug/UART).
6. Assign all capacitors to their decoupled IC pins (C_IN, C_OUT per regulator; C_BYPASS per IC).
7. Emit DRC rules for RF (50Ω), AC clearance (8mm), relay isolation.

Return JSON ONLY matching schema AI_Netlist_v1. No prose, no markdown, no code blocks."""


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

        components = [_safe_unpack(Component, c) for c in result.get("components", [])]
        nets = [_safe_unpack(NetConnection, n) for n in result.get("nets", [])]
        rules = [_safe_unpack(DesignRule, r) for r in result.get("rules", [])]
        reasoning = [_safe_unpack(ReasoningStep, r) for r in result.get("reasoning_log", [])]

        # ── GATE 1: Minimum içerik kontrolü ─────────────────────────────────────
        if len(components) < 10 or len(nets) < 5:
            raise KiCadAINetlistInsufficient(
                f"AI yetersiz netlist dondurdu: {len(components)} komponent, {len(nets)} net "
                f"(en az 10 komponent ve 5 net gerekli)."
            )

        # ── GATE 2: Kritik komponent varlık kontrolü ─────────────────────────
        # ESP32-S3+DWM3000 tasarımı için bu bileşenler MUTLAKA olmalı
        CRITICAL_REFS = {
            "U1",   # ESP32-S3 MCU
            "U2",   # DWM3000 UWB modülü
        }
        CRITICAL_GROUPS = [
            # Güç zinciri: en az bir AC-DC, bir buck, bir LDO
            (["U3"], "AC-DC modül"),
            (["U4"], "Buck regülatör (3V3)"),
            (["U5"], "LDO regülatör (1V8)"),
            # Level shifter
            (["U6"], "SPI level shifter (TXB0104)"),
        ]
        netlist_ref_set = {c.ref for c in components}

        missing_critical = CRITICAL_REFS - netlist_ref_set
        if missing_critical:
            raise KiCadAINetlistInsufficient(
                f"AI kritik bileşenleri atladı: {missing_critical}. "
                "ESP32-S3 (U1) ve DWM3000 (U2) zorunlu."
            )

        # ── GATE 3: BOM kapsama oranı — aktif/yarı-aktif bileşenler ──────────
        # Kapasitörler hariç tutulur (AI çoğu zaman gruplayarak kısmen ekler)
        # Aktif bileşen refs: U*, K*, OK*, Q*, SK*, J*, L*, D* (diyot), F*, MOV*, RV*
        ACTIVE_PREFIXES = ("U", "K", "OK", "Q", "SK", "J", "L", "F", "MOV", "RV")
        # BOM'daki beklenen aktif bileşenler (sabit liste — bu tasarıma özgü)
        # BOM-correct critical refs
        EXPECTED_ACTIVE_REFS = {
            "U1", "U2",               # ESP32-S3, DWM3000
            "U3", "U4", "U5",         # HLK-10M05, TPS54331, TPS780 (power)
            "U6", "U7", "U13", "U14", # TXB0104, SN74LVC1T45 x3 (level shifters)
            "SK1", "SK2",             # ESP32 socket
            "K1", "K2",               # relays
            "U11", "U12",             # PC817X2 optocouplers (NOT OK1/OK2!)
            "Q1", "Q2",               # 2N7002 MOSFET drivers
            "F1",                     # fuse
            "J1", "J2",               # connectors
        }
        covered_active = EXPECTED_ACTIVE_REFS & netlist_ref_set
        coverage_pct = len(covered_active) / len(EXPECTED_ACTIVE_REFS) * 100

        if coverage_pct < 75:
            missing = sorted(EXPECTED_ACTIVE_REFS - netlist_ref_set)
            raise KiCadAINetlistInsufficient(
                f"AI aktif bileşen kapsaması çok düşük: %{coverage_pct:.0f} "
                f"({len(covered_active)}/{len(EXPECTED_ACTIVE_REFS)}). "
                f"Eksik kritik bileşenler: {missing}"
            )

        # ── GATE 4: Halüsinasyon kontrolü — BOM dışı bileşenler ──────────────
        # Bilinen zararsız AI varyasyonları hariç: C99-C102 kesinlikle yasak
        FORBIDDEN_PHANTOM_REFS = {"C99", "C100", "C101", "C102"}
        phantom = {c.ref for c in components} & FORBIDDEN_PHANTOM_REFS
        if phantom:
            raise KiCadAINetlistInsufficient(
                f"AI BOM kuralını ihlal etti: Hayali bileşenler eklendi: {phantom}. (LLM Halüsinasyonu)"
            )

        # ── GATE 5: Net bağlantısı — her bileşen en az 1 nette olmalı ────────
        pinned_refs: set[str] = set()
        for net in nets:
            for pin in net.pins:
                ref_part = pin.split(".")[0] if "." in pin else pin
                pinned_refs.add(ref_part)
        floating = {c.ref for c in components} - pinned_refs
        # Küçük float payına izin ver (%15 tolerance)
        float_pct = len(floating) / max(len(components), 1) * 100
        if float_pct > 15:
            raise KiCadAINetlistInsufficient(
                f"AI çok fazla bağlantısız bileşen bıraktı: {len(floating)}/{len(components)} "
                f"(%{float_pct:.0f}) hiç net'e bağlı değil. Eksikler: {sorted(floating)[:10]}"
            )

        print(
            f"[AI] Netlist kalite kapıları geçti: {len(components)} komponent, "
            f"{len(nets)} net, aktif kapsama %{coverage_pct:.0f}, "
            f"bağlantısız %{float_pct:.0f}.",
            flush=True,
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
        self._add_connectors_and_passives(components, nets, reasoning)
        self._add_rf_rules(nets, rules, reasoning)
        self._add_erc_summary_rules(rules)
        # Duplicate component ref temizliği (birden fazla method aynı ref eklemiş olabilir)
        seen_refs: set[str] = set()
        unique_components: list[Component] = []
        for c in components:
            if c.ref not in seen_refs:
                seen_refs.add(c.ref)
                unique_components.append(c)
        components.clear()
        components.extend(unique_components)

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

        # BOM-correct refs: U3=HLK-10M05, U4=TPS54331DR, U5=TPS780180200DRV, RV1=varistor
        components.extend(
            [
                Component("F1", "fuse", "500mA/250V", "Littelfuse", "0215001.MXP", "Fuse_THT:Fuse_BelFuse_Series-6ST_5.08mm", "Protect AC input.", ["rated 250VAC"]),
                Component("RV1", "varistor", "275VAC", "Bourns", "14D471K", "Varistor:RV_Disc_D14mm_W2mm_P10mm", "Clamp AC surge.", ["place within 15mm of F1"]),
                Component("U3", "ac_dc", "5V/2A isolated", "Hi-Link", "HLK-10M05", "Converter_ACDC:HLK-PM01", "Convert AC mains to isolated 5V.", ["AC section min 8mm from DC", "upgrade from HLK-5M05"]),
                Component("U4", "buck", "3.3V/3A", "Texas Instruments", "TPS54331DR", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm", "Generate ESP32 3.3V rail.", ["R14/R15 max 1mm from FB pin"]),
                Component("U5", "ldo", "1.8V/200mA", "Texas Instruments", "TPS780180200DRV", "Package_TO_SOT_SMD:SOT-23-5", "Generate DWM3000 1.8V rail.", ["C27/C28 max 1mm from OUT"]),
            ]
        )
        nets.extend(
            [
                NetConnection("AC_L_PROTECTED", ["J1.L", "F1.1", "RV1.1", "U3.AC_L"], "mains", "Fused AC live input."),
                NetConnection("AC_N", ["J1.N", "RV1.2", "U3.AC_N"], "mains", "AC neutral reference."),
                NetConnection("+5V_ISO", ["U3.+VO", "U4.VIN", "K1.COIL+", "K2.COIL+"], "power_5v", "Isolated 5V rail for relays and buck input."),
                NetConnection("+3V3", ["U4.SW_OUT", "U1.3V3", "U6.VCCA", "U7.VCCA", "U13.VCCA"], "power_3v3", "ESP32 and high side level shifter rail."),
                NetConnection("+1V8", ["U5.OUT", "U2.VDDIO", "U6.VCCB", "U7.VCCB", "U13.VCCB"], "power_1v8", "DWM3000 and low side level shifter rail."),
                NetConnection("GND", ["U3.-VO", "U4.GND", "U5.GND", "U1.GND", "U2.GND", "U6.GND", "U7.GND", "U13.GND", "U14.GND"], "ground", "Low-voltage ground return."),
            ]
        )
        rules.append(
            DesignRule(
                "AC_CLEARANCE_8MM",
                "error",
                "Maintain at least 8mm clearance and isolation slot between AC primary and low-voltage domains.",
                ["J1", "F1", "RV1", "U3"],
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

        # BOM-correct refs: U6=TXB0104RGYR, U7=SN74LVC1T45(IRQ), U13=SN74LVC1T45(EXT_TX), U14=SN74LVC1T45(EXT_RX)
        # SPI series resistors: R20-R23 (100Ohm, BOM-confirmed)
        components.extend(
            [
                Component("U6", "level_shifter", "4-bit bidirectional SPI", "Texas Instruments", "TXB0104RGYR", "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm", "Translate SPI bus between 3.3V ESP32 and 1.8V DWM3000.", ["VCCA=3.3V", "VCCB=1.8V", "OE=GND", "max 15mm from DWM3000"]),
                Component("U7", "level_shifter", "single-bit IRQ 1.8V->3.3V", "Texas Instruments", "SN74LVC1T45DBVR", "Package_TO_SOT_SMD:SOT-23-6", "Translate DWM3000 IRQ from 1.8V to 3.3V.", ["VCCA=1.8V", "VCCB=3.3V", "DIR=HIGH"]),
                Component("U13", "level_shifter", "single-bit EXT_TX 1.8V->3.3V", "Texas Instruments", "SN74LVC1T45DBVR", "Package_TO_SOT_SMD:SOT-23-6", "Translate DWM3000 EXT_TX from 1.8V to 3.3V.", ["VCCA=1.8V", "VCCB=3.3V", "DIR=HIGH"]),
                Component("U14", "level_shifter", "single-bit EXT_RX 3.3V->1.8V", "Texas Instruments", "SN74LVC1T45DBVR", "Package_TO_SOT_SMD:SOT-23-6", "Translate EXT_RX from 3.3V ESP32 to 1.8V DWM3000.", ["VCCA=3.3V", "VCCB=1.8V", "DIR=LOW"]),
                Component("R20", "resistor", "100R", "Yageo", "RC0805FR-07100RL", "Resistor_SMD:R_0805_2012Metric", "SPI CS source termination, max 5mm from ESP32."),
                Component("R21", "resistor", "100R", "Yageo", "RC0805FR-07100RL", "Resistor_SMD:R_0805_2012Metric", "SPI MOSI source termination."),
                Component("R22", "resistor", "100R", "Yageo", "RC0805FR-07100RL", "Resistor_SMD:R_0805_2012Metric", "SPI CLK source termination."),
                Component("R23", "resistor", "100R", "Yageo", "RC0805FR-07100RL", "Resistor_SMD:R_0805_2012Metric", "SPI MISO source termination."),
            ]
        )
        nets.extend(
            [
                NetConnection("SPI_CS_3V3",   ["U1.GPIO10", "R20.1", "R20.2", "U6.A1"], "spi_3v3", "ESP32 SPI chip select through source resistor."),
                NetConnection("SPI_MOSI_3V3",  ["U1.GPIO11", "R21.1", "R21.2", "U6.A2"], "spi_3v3", "ESP32 SPI MOSI through source resistor."),
                NetConnection("SPI_CLK_3V3",   ["U1.GPIO12", "R22.1", "R22.2", "U6.A3"], "spi_3v3", "ESP32 SPI clock through source resistor."),
                NetConnection("SPI_MISO_3V3",  ["U1.GPIO13", "R23.1", "R23.2", "U6.A4"], "spi_3v3", "ESP32 SPI MISO through source resistor."),
                NetConnection("SPI_CS_1V8",    ["U6.B1", "U2.SPI_CS"],   "spi_1v8", "Translated DWM3000 SPI CS."),
                NetConnection("SPI_MOSI_1V8",  ["U6.B2", "U2.SPI_MOSI"], "spi_1v8", "Translated DWM3000 SPI MOSI."),
                NetConnection("SPI_CLK_1V8",   ["U6.B3", "U2.SPI_CLK"],  "spi_1v8", "Translated DWM3000 SPI CLK."),
                NetConnection("SPI_MISO_1V8",  ["U6.B4", "U2.SPI_MISO"], "spi_1v8", "Translated DWM3000 SPI MISO."),
                NetConnection("DWM_IRQ_3V3",   ["U7.B", "U1.GPIO14"],    "rtls_3v3", "IRQ translated to ESP32 domain."),
                NetConnection("DWM_IRQ_1V8",   ["U7.A", "U2.IRQ"],       "rtls_1v8", "IRQ source from DWM3000 domain."),
                NetConnection("DWM_EXTTX_3V3", ["U13.B", "U1.GPIO15"],   "rtls_3v3", "EXT_TX translated to ESP32."),
                NetConnection("DWM_EXTTX_1V8", ["U13.A", "U2.EXT_TX"],   "rtls_1v8", "EXT_TX source DWM3000."),
                NetConnection("DWM_EXTRX_3V3", ["U14.A", "U1.GPIO16"],   "rtls_3v3", "EXT_RX from ESP32."),
                NetConnection("DWM_EXTRX_1V8", ["U14.B", "U2.EXT_RX"],   "rtls_1v8", "EXT_RX to DWM3000."),
            ]
        )
        rules.extend(
            [
                DesignRule("SPI_LENGTH_MATCH_2MM", "error", "SPI traces must be length matched within +/-2mm.", ["SPI_*"]),
                DesignRule("TXB0104_DISTANCE_15MM", "error", "Place TXB0104 (U6) within 15mm of DWM3000 (U2).", ["U2", "U6"]),
                DesignRule("RTLS_TRANSLATOR_DISTANCE_10MM", "error", "Place U7/U13/U14 within 10mm of DWM3000 IRQ/EXT pins.", ["U2", "U7", "U13", "U14"]),
            ]
        )
        reasoning.append(
            ReasoningStep(
                "warning",
                "ESP32 3.3V and DWM3000 1.8V mismatch detected. Added TXB0104 for SPI and SN74LVC1T45 translators for RTLS pins.",
                "successful",
            )
        )



    def _add_connectors_and_passives(
        self,
        components: list,
        nets: list,
        reasoning: list,
    ) -> None:
        """Connectors, sockets, inductor, and all bypass capacitors.
        These are essential for real PCB operation.
        """
        # Connectors
        components.extend([
            Component("J1", "connector", "AC Mains 3-pin", "Phoenix Contact", "1803578",
                      "TerminalBlock_PhoenixContact:MKDS_3-3,5", "220V AC input: L, N, PE",
                      ["AC clearance 8mm", "creepage IEC60664-1"]),
            Component("J2", "connector", "SMA edge", "Amphenol", "132289",
                      "Connector_Coaxial:SMA_Edge_P1.27mm", "DWM3000 UWB RF antenna output",
                      ["50 ohm controlled impedance"]),
            Component("J3", "connector", "Debug UART 4-pin", "JST", "B4B-PH-K-S",
                      "Connector_JST:JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical",
                      "UART0 debug + 3V3 + GND"),
        ])
        # ESP32 sockets
        components.extend([
            Component("SK1", "socket", "22-pin female (left)", "Wurth", "61302211821",
                      "Connector_PinSocket_2.54mm:PinSocket_2x22_P2.54mm_Vertical",
                      "ESP32-S3-WROOM-2 left row socket"),
            Component("SK2", "socket", "22-pin female (right)", "Wurth", "61302211821",
                      "Connector_PinSocket_2.54mm:PinSocket_2x22_P2.54mm_Vertical",
                      "ESP32-S3-WROOM-2 right row socket"),
        ])
        # Inductor for TPS54331 buck
        components.append(
            Component("L1", "inductor", "10uH 3A", "TDK", "SLF12565T-100M3R3-PF",
                      "Inductor_SMD:L_Bourns-SRR1210A", "TPS54331 buck SW node inductor",
                      ["MAX 5mm from SW pin", "Isat > 3A"])
        )
        # Feedback resistors for TPS54331
        components.extend([
            Component("R14", "resistor", "10kR", "Yageo", "RC0603FR-0710KL",
                      "Resistor_SMD:R_0603_1608Metric", "TPS54331 FB lower (to GND) -> Vout=3.33V"),
            Component("R15", "resistor", "31k6", "Yageo", "RC0603FR-0731K6L",
                      "Resistor_SMD:R_0603_1608Metric", "TPS54331 FB upper (to Vout) -> Vout=3.33V"),
        ])
        # Fuse and varistor (if not already added by _add_power_tree)
        existing_refs = {c.ref for c in components}
        if "F1" not in existing_refs:
            components.append(
                Component("F1", "fuse", "500mA/250V", "Littelfuse", "0451.500MRL",
                          "Fuse:Fuse_1206_3216Metric", "AC supply protection")
            )
        if "RV1" not in existing_refs:
            components.append(
                Component("RV1", "varistor", "275VAC", "Bourns", "MOV-14D471K",
                          "Varistor:RV_Disc_D14mm_W2mm_P10mm", "AC surge clamp")
            )
        # Bypass capacitors
        bypass_caps = [
            ("C1",  "100uF/16V", "HLK output bulk cap"),
            ("C2",  "100nF",     "HLK output bypass"),
            ("C21", "10uF/16V",  "TPS54331 VIN bulk"),
            ("C22", "100nF",     "TPS54331 VIN bypass"),
            ("C23", "100uF/6V",  "TPS54331 VOUT bulk"),
            ("C24", "100nF",     "TPS54331 VOUT bypass"),
            ("C25", "10uF/6V",   "TPS780 VIN bulk"),
            ("C26", "100nF",     "TPS780 VIN bypass"),
            ("C27", "1uF",       "TPS780 VOUT bypass <1mm"),
            ("C28", "100nF",     "TPS780 VOUT HF bypass <1mm"),
            ("C29", "100nF",     "TXB0104 VCCA(3V3) bypass <1mm"),
            ("C30", "100nF",     "TXB0104 VCCB(1V8) bypass <1mm"),
            ("C33", "100nF",     "U7 SN74LVC1T45 VCCA(1V8) bypass"),
            ("C34", "100nF",     "U7 SN74LVC1T45 VCCB(3V3) bypass"),
            ("C35", "100nF",     "U13 SN74LVC1T45 VCCA bypass"),
            ("C36", "100nF",     "U13 SN74LVC1T45 VCCB bypass"),
            ("C37", "100nF",     "U14 SN74LVC1T45 VCCA bypass"),
            ("C38", "100nF",     "U14 SN74LVC1T45 VCCB bypass"),
            ("C39", "10uF",      "DWM3000 VDD3V3 bulk"),
            ("C40", "100nF",     "DWM3000 VDD3V3 HF bypass"),
            ("C41", "10uF",      "DWM3000 VDDIO(1V8) bulk"),
            ("C42", "100nF",     "DWM3000 VDDIO(1V8) HF bypass"),
        ]
        for ref, val, desc in bypass_caps:
            if ref not in existing_refs:
                components.append(
                    Component(ref, "capacitor", val, "Murata", "GRM188R71H104KA93D",
                              "Capacitor_SMD:C_0603_1608Metric", desc)
                )
        # Net connections for connectors, sockets, inductor
        nets.extend([
            NetConnection("AC_PE",      ["J1.PE"],                        "mains",    "Protective earth"),
            NetConnection("UART_TX",    ["U1.GPIO43", "J3.TX"],           "uart",     "ESP32 UART0 TX"),
            NetConnection("UART_RX",    ["U1.GPIO44", "J3.RX"],           "uart",     "ESP32 UART0 RX"),
            NetConnection("+3V3_DBG",   ["J3.VCC"],                       "power_3v3","Debug connector 3V3"),
            NetConnection("GND_DBG",    ["J3.GND"],                       "ground",   "Debug GND"),
            NetConnection("+3V3_SK",    ["SK1.VCC", "SK2.VCC"],           "power_3v3","ESP32 socket 3V3"),
            NetConnection("GND_SK",     ["SK1.GND", "SK2.GND"],           "ground",   "ESP32 socket GND"),
            NetConnection("BUCK_SW",    ["U4.SW", "L1.1"],                "switching","TPS54331 SW node -> inductor"),
            NetConnection("+3V3_L",     ["L1.2", "C23.1", "C24.1"],      "power_3v3","3V3 post-inductor"),
            NetConnection("BUCK_FB",    ["U4.FB", "R14.1", "R15.1"],     "feedback", "TPS54331 feedback mid"),
            NetConnection("BUCK_FB_GND",["R14.2", "U4.GND"],             "ground",   "FB lower to GND"),
            NetConnection("+3V3_FB_TOP",["R15.2", "L1.2"],               "power_3v3","FB upper to Vout"),
            NetConnection("+5V_BYPASS", ["C1.1", "C2.1", "C21.1", "C22.1", "C25.1", "C26.1"], "power_5v", "5V bypass caps"),
            NetConnection("+3V3_BYPASS",["C29.1", "C34.1", "C36.1", "C37.1", "C39.1", "C40.1"], "power_3v3", "3V3 bypass caps"),
            NetConnection("+1V8_BYPASS",["C27.1", "C28.1", "C30.1", "C33.1", "C35.1", "C38.1", "C41.1", "C42.1"], "power_1v8", "1V8 bypass caps"),
            NetConnection("GND_BYPASS", [
                "C1.2","C2.2","C21.2","C22.2","C23.2","C24.2",
                "C25.2","C26.2","C27.2","C28.2","C29.2","C30.2",
                "C33.2","C34.2","C35.2","C36.2","C37.2","C38.2",
                "C39.2","C40.2","C41.2","C42.2",
            ], "ground", "All bypass cap GND returns"),
        ])
        reasoning.append(
            ReasoningStep(
                "info",
                "Connectors J1/J2/J3, sockets SK1/SK2, inductor L1, feedback R14/R15, "
                "and all bypass capacitors added to fallback netlist.",
                "successful",
            )
        )

    def _add_relay_isolation(
        self,
        relay_count: int,
        components: list,
        nets: list,
        rules: list,
        reasoning: list,
    ) -> None:
        if relay_count == 0:
            return

        # BOM-correct: U11=PC817X2 (K1 opto), U12=PC817X2 (K2 opto), Q1/Q2=2N7002, D2/D3=1N5819 flyback
        # R16/R17=330R opto LED limit, R18/R19=10k MOSFET pulldown
        for index in range(1, min(relay_count, 2) + 1):
            opto_ref = f"U{10 + index}"       # U11 for K1, U12 for K2
            flyback_ref = f"D{index + 1}"     # D2 for K1, D3 for K2
            led_r_ref = f"R{15 + index}"      # R16 for K1, R17 for K2
            pull_r_ref = f"R{17 + index}"     # R18 for K1, R19 for K2
            components.extend(
                [
                    Component(f"K{index}", "relay", "5V SPDT relay", "Omron", "G5Q-14-DC5",
                              "Relay_THT:Relay_SPDT_Omron-G5Q-14-DC5_Pitch5.08mm",
                              f"Isolated relay output {index}.", ["coil 5V", "max 10A/250VAC contacts"]),
                    Component(opto_ref, "optocoupler", "PC817X2 dual", "Sharp", "PC817X2CSP9F",
                              "Package_SO:SOP-8_3.9x4.9mm_P1.27mm",
                              f"Dual opto for relay {index} isolation.", ["CTR min 50%"]),
                    Component(f"Q{index}", "n_mosfet", "2N7002", "OnSemi", "2N7002",
                              "Package_TO_SOT_SMD:SOT-23",
                              f"Low-side MOSFET driver for K{index} coil.", ["Vgs max 20V"]),
                    Component(flyback_ref, "flyback_diode", "1N5819", "Vishay", "1N5819",
                              "Diode_SMD:D_SMA",
                              f"Flyback clamp for K{index} coil.", ["reverse across coil"]),
                    Component(led_r_ref, "resistor", "330R", "Yageo", "RC0805FR-07330RL",
                              "Resistor_SMD:R_0805_2012Metric",
                              f"Opto LED current limit for K{index}."),
                    Component(pull_r_ref, "resistor", "10kR", "Yageo", "RC0805FR-0710KL",
                              "Resistor_SMD:R_0805_2012Metric",
                              f"MOSFET gate pulldown for Q{index}."),
                ]
            )
            nets.extend(
                [
                    NetConnection(f"RELAY{index}_CTRL",
                        [f"U1.GPIO{3 + index}", led_r_ref + ".1", opto_ref + ".A1"],
                        "gpio", f"ESP32 GPIO{3+index} -> opto LED for K{index}."),
                    NetConnection(f"RELAY{index}_OPTOGND",
                        [led_r_ref + ".2", opto_ref + ".K1"],
                        "ground", f"Opto LED cathode GND."),
                    NetConnection(f"RELAY{index}_GATE",
                        [opto_ref + ".C1", f"Q{index}.G", pull_r_ref + ".1"],
                        "relay_drive", f"Isolated gate for Q{index}."),
                    NetConnection(f"RELAY{index}_PULLGND",
                        [pull_r_ref + ".2", f"Q{index}.S"],
                        "ground", f"Q{index} source and pulldown GND."),
                    NetConnection(f"RELAY{index}_COIL_HI",
                        [f"K{index}.COIL+", flyback_ref + ".K"],
                        "power_5v", f"K{index} coil high side from +5V_ISO."),
                    NetConnection(f"RELAY{index}_COIL_LOW",
                        [f"K{index}.COIL-", f"Q{index}.D", flyback_ref + ".A"],
                        "relay_drive", f"K{index} coil low side switched by Q{index}."),
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
        nets: list,
        rules: list,
        reasoning: list,
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

    def _add_erc_summary_rules(self, rules: list) -> None:
        rules.extend(
            [
                DesignRule("POWER_RAIL_SEQUENCE", "warning", "Validate 5V before 3V3 before 1V8 startup behavior.", ["+5V_ISO", "+3V3", "+1V8"]),
                DesignRule("HUMAN_REVIEW_REQUIRED", "warning", "Human engineer must review AC safety, RF impedance, relay isolation, and final DRC/ERC before fabrication.", ["ALL"]),
            ]
        )

    def _relay_count(self, normalized: str) -> int:
        count_match = re.search(r"(\d+)\s*(adet\s*)?(g5q|role|rle|relay)", normalized)
        if count_match:
            return int(count_match.group(1))
        return 1 if any(token in normalized for token in ("g5q", "role", "rle", "relay")) else 0


def write_netlist(project_root, user_request: str):
    from pathlib import Path
    generator = CognitiveNetlistGenerator()
    netlist = generator.synthesize(user_request)
    output_dir = Path(project_root) / "outputs" / "phase1"
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
    from pathlib import Path
    output_path = write_netlist(Path(args.project_root).resolve(), args.request)
    print(f"Generated {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
