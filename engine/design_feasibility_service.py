from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BOARD_WIDTH_MM = 130.0
DEFAULT_BOARD_HEIGHT_MM = 46.0
MAX_PCB_MOUNTED_FOR_FIXED_130X46 = 120
MAX_ROUTING_UTILIZATION = 2.0

# ── Density thresholds for Engineering Feasibility Gate ──────────────────────
DENSITY_LAYER_UPGRADE = 0.40   # D > 0.40 → auto-upgrade to 4 layers
DENSITY_WARN = 0.65            # D > 0.65 → warn: board too small
DENSITY_BLOCK = 0.80           # D > 0.80 → pipeline block: physical limit
DENSITY_SAFETY_FACTOR = 2.2    # suggested min board area = A_comp * factor

NON_PCB_TYPES = {"virtual_module"}
OPTIONAL_TYPES = {"test_point", "led"}
RISK_TYPES = {"ac_dc", "relay", "uwb_module", "antenna", "socket", "connector"}

# Fallback area by type when footprint dimensions cannot be parsed.
AREA_BY_TYPE_MM2 = {
    "ac_dc": 900.0,
    "relay": 420.0,
    "socket": 360.0,
    "uwb_module": 90.0,
    "antenna": 220.0,
    "connector": 120.0,
    "fuse": 160.0,
    "varistor": 180.0,
    "buck": 70.0,
    "ldo": 35.0,
    "level_shifter": 30.0,
    "ic": 70.0,
    "optocoupler": 90.0,
    "n_mosfet": 18.0,
    "diode": 28.0,
    "flyback_diode": 45.0,
    "ferrite_bead": 12.0,
    "inductor": 160.0,
    "crystal": 22.0,
    "battery": 320.0,
    "switch": 70.0,
    "test_point": 16.0,
    "led": 20.0,
    "resistor": 12.0,
    "capacitor": 12.0,
    "component": 55.0,
}

# ── Known footprint dimensions (W × H in mm) for real area calculation ───────
# Key: substring that appears in the Package/Footprint BOM column or KiCad lib.
_FOOTPRINT_DIMENSIONS_MM: dict[str, tuple[float, float]] = {
    # SMD passives
    "0201": (0.6, 0.3),
    "0402": (1.0, 0.5),
    "0603": (1.6, 0.8),
    "0805": (2.0, 1.25),
    "1206": (3.2, 1.6),
    "1210": (3.2, 2.5),
    "2010": (5.0, 2.5),
    "2512": (6.3, 3.2),
    # SMD diode
    "sod-323": (1.7, 1.25),
    "sma": (5.2, 2.6),     # SMA diode package (not SMA connector)
    "smb": (5.3, 3.6),
    "smc": (7.8, 5.2),
    # Transistor / IC packages
    "sot-23": (2.9, 1.3),
    "sot-23-5": (2.9, 1.6),
    "sot-23-6": (2.9, 1.6),
    "sot-223": (6.5, 3.5),
    "soic-8": (3.9, 4.9),
    "so-8": (3.9, 4.9),
    "ssop-8": (3.0, 5.3),
    "dip-4": (7.6, 6.3),
    "vqfn-16": (4.0, 4.0),
    "lqfp-48": (7.0, 7.0),
    "qfn-48": (7.0, 7.0),
    # Specific modules
    "lga-28": (13.9, 22.3),  # DWM3000
    "2020": (2.0, 2.0),       # WS2812B-2020
    "5x20mm": (5.0, 20.0),    # Glass fuse
    "14mm": (14.0, 5.0),      # 14mm disc varistor
    "cr2032": (24.0, 24.0),   # Coin cell holder
    "6x6mm": (6.0, 6.0),     # Tactile switch
    # Connectors
    "pinheader_1x4": (2.54, 10.16),
    "pinheader_1x6": (2.54, 15.24),
    "pinsocket_1x22": (2.54, 55.88),
    "pinsocket_2x22": (5.08, 55.88),
    "5.0mm": (15.0, 8.0),     # 3-pin screw terminal 5mm
    "3.5mm": (10.5, 7.0),     # 3-pin screw terminal 3.5mm
    "hr911105a": (21.0, 16.0), # RJ45 w/ magnetics
    "type-c": (9.0, 7.5),     # USB-C connector
    "pj-002a": (14.0, 9.0),   # DC power jack
    "edge mount": (10.0, 10.0), # SMA connector
    # Power modules
    "hlk-10m05": (33.0, 20.0),
    "hlk-5m05": (33.0, 20.0),
    "pcb module": (33.0, 20.0),
    # Relay
    "relay_spdt_omron": (20.0, 10.0),
    "relay_tht": (20.0, 10.0),
    # Inductor
    "10x10mm": (10.0, 10.0),
    "cdrh104r": (10.0, 10.0),
    # Crystal
    "3.2x2.5": (3.2, 2.5),
    # Test point
    "1.27mm": (1.27, 1.27),
    "testpoint": (1.27, 1.27),
}


@dataclass(frozen=True)
class FeasibilityAction:
    id: str
    label: str
    consequence: str


@dataclass(frozen=True)
class DesignFeasibilityReport:
    schema: str
    generated_at: str
    status: str
    board_size_mm: tuple[float, float]
    board_area_mm2: float
    pcb_mounted_count: int
    total_component_count: int
    estimated_component_area_mm2: float
    estimated_routing_utilization: float
    fixed_board_constraint: bool
    high_risk_blocks: dict[str, int]
    optional_reduction_candidates: dict[str, list[str]]
    blocker_summary: str
    recommended_actions: list[FeasibilityAction]
    # ── New density-gate fields ──────────────────────────────────────────────
    density_ratio: float = 0.0
    auto_layer_upgrade: bool = False
    suggested_layer_count: int = 2
    suggested_board_area_mm2: float = 0.0
    density_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DesignFeasibilityService:
    """Pre-KiCad feasibility gate for real-world PCB generation.

    This is deliberately conservative. It does not silently override a user's
    mechanical constraint; it reports when the requested electrical scope and
    board envelope are physically inconsistent.
    """

    def audit(
        self,
        netlist_file: Path,
        *,
        output: Path | None = None,
        bom_file: Path | None = None,
        config_file: Path | None = None,
    ) -> DesignFeasibilityReport:
        data = json.loads(netlist_file.read_text(encoding="utf-8"))
        components = list(data.get("components") or [])
        width, height = self._board_size_from_netlist(data, config_file)
        board_area = round(width * height, 2)
        pcb_components = [c for c in components if self._is_pcb_mounted(c)]

        # ── Real footprint-based density calculation ─────────────────────────
        bom_footprints = self._load_bom_footprints(bom_file) if bom_file else {}
        component_area = round(
            sum(self._component_area_real(c, bom_footprints) for c in pcb_components), 2
        )
        utilization = round(component_area / board_area, 3) if board_area else 999.0
        density = round(component_area / board_area, 4) if board_area else 999.0

        # ── Density-based decisions ──────────────────────────────────────────
        auto_layer_upgrade = density > DENSITY_LAYER_UPGRADE
        suggested_layers = 4 if auto_layer_upgrade else 2
        suggested_board_area = round(component_area * DENSITY_SAFETY_FACTOR, 1)

        fixed_board = self._has_fixed_board_constraint(data)
        high_risk = self._count_high_risk_blocks(pcb_components)
        optional = self._optional_candidates(pcb_components)
        status = self._status(
            width=width,
            height=height,
            pcb_mounted_count=len(pcb_components),
            utilization=utilization,
            fixed_board=fixed_board,
            density=density,
        )
        density_details = {
            "component_area_mm2": component_area,
            "board_area_mm2": board_area,
            "density_ratio": density,
            "threshold_layer_upgrade": DENSITY_LAYER_UPGRADE,
            "threshold_warn": DENSITY_WARN,
            "threshold_block": DENSITY_BLOCK,
            "auto_layer_upgrade_triggered": auto_layer_upgrade,
        }

        report = DesignFeasibilityReport(
            schema="DESIGN_FEASIBILITY_V2",
            generated_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            status=status,
            board_size_mm=(width, height),
            board_area_mm2=board_area,
            pcb_mounted_count=len(pcb_components),
            total_component_count=len(components),
            estimated_component_area_mm2=component_area,
            estimated_routing_utilization=utilization,
            fixed_board_constraint=fixed_board,
            high_risk_blocks=high_risk,
            optional_reduction_candidates=optional,
            blocker_summary=self._summary(status, len(pcb_components), width, height, utilization, fixed_board, density),
            recommended_actions=self._actions(status, fixed_board, density, suggested_board_area),
            density_ratio=density,
            auto_layer_upgrade=auto_layer_upgrade,
            suggested_layer_count=suggested_layers,
            suggested_board_area_mm2=suggested_board_area,
            density_details=density_details,
        )
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return report

    def _board_size_from_netlist(
        self, data: dict[str, Any], config_file: Path | None = None,
    ) -> tuple[float, float]:
        # Priority 1: Alan 3 YAML global_pcb_rules.board_size (mutlak otorite)
        prompt = str(data.get("source_prompt", ""))
        yaml_parsed = self._parse_board_size_from_yaml(prompt)
        if yaml_parsed is not None:
            print(f"[FEASIBILITY] Board size from Alan 3 YAML global_pcb_rules (mutlak otorite): {yaml_parsed[0]}×{yaml_parsed[1]}mm", flush=True)
            return yaml_parsed
        # Priority 2: project_config.json fallback
        if config_file and config_file.exists():
            try:
                cfg = json.loads(config_file.read_text(encoding="utf-8"))
                raw = cfg.get("board_size_mm")
                parsed = self._parse_size(raw)
                if parsed is not None:
                    print(f"[FEASIBILITY] Board size from project_config.json fallback: {parsed[0]}×{parsed[1]}mm", flush=True)
                    return parsed
            except Exception:
                pass
        # Priority 3: netlist top-level keys
        for key in ("board_size_mm", "board_dimensions_mm"):
            raw = data.get(key)
            parsed = self._parse_size(raw)
            if parsed is not None:
                return parsed
        # Priority 4: generic text search in source_prompt
        parsed = self._parse_board_size_text(prompt)
        if parsed is not None:
            return parsed
        print(f"[FEASIBILITY] Board size fallback to defaults: {DEFAULT_BOARD_WIDTH_MM}×{DEFAULT_BOARD_HEIGHT_MM}mm", flush=True)
        return DEFAULT_BOARD_WIDTH_MM, DEFAULT_BOARD_HEIGHT_MM

    def _parse_size(self, raw: Any) -> tuple[float, float] | None:
        if isinstance(raw, dict):
            width = raw.get("width") or raw.get("w")
            height = raw.get("height") or raw.get("h")
            if width and height:
                return float(width), float(height)
        if isinstance(raw, (list, tuple)) and len(raw) >= 2:
            return float(raw[0]), float(raw[1])
        text = str(raw or "")
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*mm?\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*mm", text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ".")), float(match.group(2).replace(",", "."))
        return None

    def _parse_board_size_from_yaml(self, text: str) -> tuple[float, float] | None:
        """Extract board size from YAML-like global_pcb_rules.board_size section.

        The source_prompt contains escaped newlines (\\n).  We look for the
        structured pattern:
            board_size:
              width_mm: <float>
              height_mm: <float>
        """
        # Normalise escaped newlines so regex can work line by line
        norm = text.replace("\\n", "\n")
        # Match width_mm and height_mm following a board_size: header
        m_width = re.search(
            r"board_size:.*?width_mm:\s*([\d.]+)",
            norm, re.DOTALL,
        )
        m_height = re.search(
            r"board_size:.*?height_mm:\s*([\d.]+)",
            norm, re.DOTALL,
        )
        if m_width and m_height:
            try:
                return float(m_width.group(1)), float(m_height.group(1))
            except ValueError:
                pass
        return None

    def _parse_board_size_text(self, text: str) -> tuple[float, float] | None:
        context_terms = ("board", "pcb", "boyut", "kart")
        for line in text.splitlines():
            lowered = line.lower()
            if any(term in lowered for term in context_terms):
                parsed = self._parse_size(line)
                if parsed is not None:
                    return parsed
        return self._parse_size(text)

    def _has_fixed_board_constraint(self, data: dict[str, Any]) -> bool:
        prompt = str(data.get("source_prompt", "")).lower()
        fixed_terms = [
            "board boyutu değişmez",
            "board boyutu degismez",
            "sabit, genişletilmez",
            "sabit, genisletilmez",
            "değiştirme",
            "degistirme",
        ]
        return any(term in prompt for term in fixed_terms)

    def _is_pcb_mounted(self, component: dict[str, Any]) -> bool:
        ctype = str(component.get("type", "")).lower()
        footprint = str(component.get("footprint", "")).lower()
        return ctype not in NON_PCB_TYPES and footprint != "not_pcb_mounted"

    def _component_area(self, component: dict[str, Any]) -> float:
        """Legacy fallback: type-based area estimate."""
        ctype = str(component.get("type", "component")).lower()
        return AREA_BY_TYPE_MM2.get(ctype, AREA_BY_TYPE_MM2["component"])

    def _component_area_real(
        self, component: dict[str, Any], bom_footprints: dict[str, str],
    ) -> float:
        """Real footprint-based area: look up W×H from package string."""
        ref = str(component.get("ref", "")).strip()
        # Try BOM Package/Footprint first, then netlist footprint field
        pkg = bom_footprints.get(ref, "") or str(component.get("footprint", ""))
        dims = self._dims_from_package(pkg)
        if dims:
            return round(dims[0] * dims[1], 2)
        # Fallback to type-based estimate
        return self._component_area(component)

    @staticmethod
    def _dims_from_package(package: str) -> tuple[float, float] | None:
        """Extract W×H from a package/footprint string using the lookup table."""
        lower = package.lower().strip()
        if not lower:
            return None
        # Direct dimension match: "33.0x20.0mm" or "10x10mm"
        m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*mm", lower)
        if m:
            return float(m.group(1)), float(m.group(2))
        # Lookup table (longest substring match wins for accuracy)
        best: tuple[float, float] | None = None
        best_len = 0
        for key, dims in _FOOTPRINT_DIMENSIONS_MM.items():
            if key in lower and len(key) > best_len:
                best = dims
                best_len = len(key)
        return best

    @staticmethod
    def _load_bom_footprints(bom_file: Path) -> dict[str, str]:
        """Load ref -> Package/Footprint from BOM CSV."""
        result: dict[str, str] = {}
        if not bom_file or not bom_file.exists():
            return result
        try:
            with bom_file.open("r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    ref_token = (row.get("Reference") or "").strip()
                    pkg = (
                        row.get("Package / Footprint")
                        or row.get("Footprint")
                        or row.get("Package")
                        or ""
                    ).strip()
                    if not ref_token or not pkg:
                        continue
                    if ref_token.startswith("==") and ref_token.endswith("=="):
                        continue
                    # Expand ranges like R10-R13
                    for ref in _expand_refs_simple(ref_token):
                        result[ref] = pkg
        except Exception:
            pass
        return result

    def _count_high_risk_blocks(self, components: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for component in components:
            ctype = str(component.get("type", "")).lower()
            if ctype in RISK_TYPES:
                counts[ctype] = counts.get(ctype, 0) + 1
        return counts

    def _optional_candidates(self, components: list[dict[str, Any]]) -> dict[str, list[str]]:
        candidates: dict[str, list[str]] = {}
        for component in components:
            ref = str(component.get("ref", ""))
            ctype = str(component.get("type", "")).lower()
            if ctype in OPTIONAL_TYPES or self._looks_optional_connector(ref, component):
                candidates.setdefault(ctype or "component", []).append(ref)
        return {key: refs[:40] for key, refs in sorted(candidates.items()) if refs}

    def _looks_optional_connector(self, ref: str, component: dict[str, Any]) -> bool:
        if str(component.get("type", "")).lower() != "connector":
            return False
        if ref in {"J1", "J1_AC", "J1_USB", "J2", "ANT1", "J3", "J4", "J18"}:
            return False
        return ref.startswith("J")

    def _status(
        self,
        *,
        width: float,
        height: float,
        pcb_mounted_count: int,
        utilization: float,
        fixed_board: bool,
        density: float = 0.0,
    ) -> str:
        # ── Density-based checks (primary gate) ─────────────────────────────
        if density > DENSITY_BLOCK:
            return "blocked"
        if density > DENSITY_WARN:
            return "review"
        # ── Legacy utilization checks ────────────────────────────────────────
        if fixed_board and (
            (width <= 130.0 and height <= 46.0 and pcb_mounted_count > MAX_PCB_MOUNTED_FOR_FIXED_130X46)
            or utilization > MAX_ROUTING_UTILIZATION
        ):
            return "review"
        if utilization > MAX_ROUTING_UTILIZATION:
            return "blocked"
        if utilization > 0.65:
            return "review"
        return "pass"

    def _summary(
        self, status: str, count: int, width: float, height: float,
        utilization: float, fixed_board: bool, density: float = 0.0,
    ) -> str:
        fixed = "fixed" if fixed_board else "flexible"
        density_pct = f"{density * 100:.1f}%"
        if status == "blocked":
            return (
                f"{count} PCB-mounted components exceed the practical envelope for a "
                f"{width:.0f}x{height:.0f}mm {fixed} board; density={density_pct}, "
                f"utilization={utilization:.2f}. Fiziksel limit aşıldı — kartı büyütmeden üretime geçilemez."
            )
        if status == "review":
            layer_msg = " Katman sayısı otomatik olarak 4'e yükseltildi." if density > DENSITY_LAYER_UPGRADE else ""
            return (
                f"{count} PCB-mounted components are dense for {width:.0f}x{height:.0f}mm; "
                f"density={density_pct}, utilization={utilization:.2f}.{layer_msg} "
                f"Engineering review required."
            )
        if density > DENSITY_LAYER_UPGRADE:
            return (
                f"{count} PCB-mounted components pass for {width:.0f}x{height:.0f}mm "
                f"(density={density_pct}). Layer count auto-upgraded to 4 for routing margin."
            )
        return f"{count} PCB-mounted components fit the feasibility gate for {width:.0f}x{height:.0f}mm (density={density_pct})."

    def _actions(
        self, status: str, fixed_board: bool,
        density: float = 0.0, suggested_area: float = 0.0,
    ) -> list[FeasibilityAction]:
        actions: list[FeasibilityAction] = []
        # Layer upgrade notification (not a blocker, just informational)
        if density > DENSITY_LAYER_UPGRADE and status != "blocked":
            actions.append(FeasibilityAction(
                id="auto_upgrade_layers",
                label="Katman sayısı 4'e yükseltildi",
                consequence=f"Yoğunluk {density * 100:.1f}% > %{DENSITY_LAYER_UPGRADE * 100:.0f} eşiği. Yönlendirme güvenliği için 4 katman kullanılacak.",
            ))
        if status != "blocked":
            return actions
        # Blocked: suggest corrective actions
        actions.extend([
            FeasibilityAction(
                id="reduce_scope",
                label="Opsiyonel bileşenleri çıkar",
                consequence="Test noktaları, debug header'lar ve kritik olmayan LED'ler kaldırılarak tekrar denenecek.",
            ),
            FeasibilityAction(
                id="split_board",
                label="Kartı ikiye böl",
                consequence="AC/röle güç bölümünü RF/lojik bölümünden ayırarak iki kart oluşturulacak.",
            ),
        ])
        if not fixed_board:
            actions.insert(
                0,
                FeasibilityAction(
                    id="allow_larger_board",
                    label="Kartı büyüt",
                    consequence=f"Önerilen minimum kart alanı: {suggested_area:.0f} mm². Aynı devre kapsamı korunacak.",
                ),
            )
        else:
            actions.append(
                FeasibilityAction(
                    id="override_board_size",
                    label="Sabit kart boyutunu geçersiz kıl",
                    consequence="Kullanıcı girdisi kartın büyümemesini istiyor — açık insan onayı gerektirir.",
                )
            )
        return actions


def _expand_refs_simple(token: str) -> list[str]:
    """Simple ref range expansion: 'R10-R13' -> ['R10','R11','R12','R13']."""
    out: list[str] = []
    normalized = token.replace("–", "-").replace("—", "-")
    for part in re.split(r"[,;\s]+", normalized):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^([A-Za-z_]+)(\d+)\s*-\s*([A-Za-z_]*)(\d+)$", part)
        if m:
            pre1, start, pre2, end = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
            prefix = pre2 if pre2 else pre1
            if prefix == pre1 and end >= start:
                out.extend(f"{prefix}{i}" for i in range(start, end + 1))
                continue
        out.append(part)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PCB design feasibility before KiCad placement.")
    parser.add_argument("--netlist-file", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--output", default="assets/generated/design_feasibility_report.json")
    parser.add_argument("--bom-file", default="BOM.csv")
    parser.add_argument("--config-file", default="project_config.json")
    args = parser.parse_args()
    report = DesignFeasibilityService().audit(
        Path(args.netlist_file),
        output=Path(args.output),
        bom_file=Path(args.bom_file),
        config_file=Path(args.config_file),
    )
    result_json = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    try:
        sys.stdout.buffer.write(result_json.encode("utf-8"))
        sys.stdout.buffer.write(b"\n")
    except (AttributeError, UnicodeEncodeError):
        print(result_json)
    return 0 if report.status in {"pass", "review"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
