from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BomEvidence:
    refs: set[str]
    part_numbers: set[str]
    raw_text: str
    ref_meta: dict[str, dict[str, str]]


def _parse_bom_csv(bom_file: Path) -> dict[str, dict[str, str]]:
    """BOM.csv -> ref -> {value, manufacturer, part_number} (aralik acilmis).

    Kullanicinin yapilandirilmis BOM'u komponent kimligi (value/MPN/uretici)
    icin otoritedir. Sadece BOM.csv yapisal olarak okunur."""
    ref_meta: dict[str, dict[str, str]] = {}
    if not bom_file.exists():
        return ref_meta
    try:
        with bom_file.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                token = (row.get("Reference") or "").strip()
                if not token:
                    continue
                meta = {
                    "value": (row.get("Value") or "").strip(),
                    "manufacturer": (row.get("Manufacturer") or "").strip(),
                    "part_number": (row.get("Part Number") or "").strip(),
                }
                for ref in _expand_ref_token(token.replace(" ", "").upper()):
                    ref_meta[ref] = meta
    except Exception:  # noqa: BLE001 — BOM bicimi beklenmedikse hizalama atlanir
        return {}
    return ref_meta


def load_bom_evidence(netlist: dict[str, Any], bom_file: Path) -> BomEvidence:
    parts: list[str] = []
    if bom_file.exists():
        parts.append(bom_file.read_text(encoding="utf-8", errors="ignore"))
    source_prompt = str(netlist.get("source_prompt", ""))
    if source_prompt:
        parts.append(source_prompt)
    raw_text = "\n".join(parts)
    return BomEvidence(
        refs=_extract_reference_tokens(raw_text),
        part_numbers=_extract_part_numbers(raw_text),
        raw_text=raw_text,
        ref_meta=_parse_bom_csv(bom_file),
    )


def normalize_design_source(netlist: dict[str, Any], bom_file: Path) -> dict[str, Any]:
    """Return a production-evidence normalized AI netlist.

    This does not invent a whole design. It resolves BOM-backed grouped
    references and known shorthand pins so evidence gates see the same source
    model that KiCad generation expects.
    """
    normalized = json.loads(json.dumps(netlist))
    components = [item for item in normalized.get("components", []) if isinstance(item, dict)]
    nets = [item for item in normalized.get("nets", []) if isinstance(item, dict)]
    evidence = load_bom_evidence(normalized, bom_file)

    _normalize_component_part_numbers(components, evidence)
    _add_missing_bom_backed_components(components, nets, evidence)
    _align_component_metadata(components, evidence)
    _normalize_net_pin_shorthands(nets, {str(c.get("ref", "")).strip() for c in components})

    normalized["components"] = components
    normalized["nets"] = nets
    return normalized


def write_normalized_design_source(netlist_file: Path, bom_file: Path, output_file: Path | None = None) -> Path:
    source = json.loads(netlist_file.read_text(encoding="utf-8"))
    normalized = normalize_design_source(source, bom_file)
    target = output_file or netlist_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def _extract_reference_tokens(text: str) -> set[str]:
    refs: set[str] = set()
    for token in re.findall(r"\b[A-Z]{1,4}\d+(?:\s*-\s*[A-Z]?\d+)?\b", text.upper()):
        refs.update(_expand_ref_token(token.replace(" ", "")))
    return refs


def _expand_ref_token(token: str) -> set[str]:
    match = re.fullmatch(r"([A-Z]+)(\d+)-(?:(?:[A-Z]+)?)(\d+)", token)
    if not match:
        return {token}
    prefix, start, end = match.groups()
    start_i = int(start)
    end_i = int(end)
    if end_i < start_i or end_i - start_i > 200:
        return {token}
    return {f"{prefix}{index}" for index in range(start_i, end_i + 1)}


def _extract_part_numbers(text: str) -> set[str]:
    candidates: set[str] = set()
    for row in csv.reader(text.splitlines()):
        for cell in row:
            value = cell.strip()
            if _looks_like_part_number(value):
                candidates.add(_part_key(value))
    for token in re.findall(r"\b[A-Z0-9][A-Z0-9._/-]{2,}\b", text.upper()):
        if _looks_like_part_number(token):
            candidates.add(_part_key(token))
    return candidates


def _looks_like_part_number(value: str) -> bool:
    if len(value) < 3:
        return False
    if " " in value:
        return False
    if not any(char.isdigit() for char in value):
        return False
    if value.upper() in {"SMD", "QFN", "SMA", "DIP", "SC70", "RELAY"}:
        return False
    return True


def _part_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def _align_component_metadata(components: list[dict[str, Any]], evidence: BomEvidence) -> None:
    """Mevcut komponentlerin value/manufacturer/part_number alanlarini
    kullanicinin BOM'una hizalar (BOM otorite). footprint KiCad-dogrulanmis
    oldugu icin DOKUNULMAZ. Boylece netlist BOM'dan sapamaz (orn. R20 IRQ
    pull-up'i 100R degil 10K kalir)."""
    for component in components:
        ref = str(component.get("ref", "")).strip()
        meta = evidence.ref_meta.get(ref)
        if not meta:
            continue
        for field in ("value", "manufacturer", "part_number"):
            bom_val = (meta.get(field) or "").strip()
            if bom_val and str(component.get(field, "")).strip().lower() != bom_val.lower():
                component[field] = bom_val


def _normalize_component_part_numbers(components: list[dict[str, Any]], evidence: BomEvidence) -> None:
    aliases = {
        "PC817": "PC817X2CSP9F",
        "SS14": "SS34-E3/57T",
        "SS34": "SS34-E3/57T",
    }
    for component in components:
        part = str(component.get("part_number", "")).strip()
        alias = aliases.get(part.upper())
        if alias and _part_key(alias) in evidence.part_numbers:
            component["part_number"] = alias


def _add_missing_bom_backed_components(
    components: list[dict[str, Any]],
    nets: list[dict[str, Any]],
    evidence: BomEvidence,
) -> None:
    refs = {str(component.get("ref", "")).strip() for component in components}
    net_refs = _net_refs(nets)
    for ref in sorted((net_refs | evidence.refs) - refs, key=_ref_sort_key):
        component = _component_for_ref(ref, evidence)
        if component is None:
            continue
        components.append(component)
        refs.add(ref)


def _net_refs(nets: list[dict[str, Any]]) -> set[str]:
    refs: set[str] = set()
    for net in nets:
        for pin in net.get("pins", []):
            ref = str(pin).partition(".")[0].strip()
            if ref:
                refs.add(ref)
    return refs


def _component_for_ref(ref: str, evidence: BomEvidence) -> dict[str, Any] | None:
    upper = ref.upper()
    if re.fullmatch(r"R\d+", upper) and upper in evidence.refs:
        return {
            "ref": upper,
            "type": "resistor",
            "value": "100R",
            "manufacturer": "Yageo",
            "part_number": "RC0603FR-07100RL",
            "footprint": "Resistor_SMD:R_0603_1608Metric",
            "reason": "BOM-backed series/source resistor.",
            "constraints": [],
        }
    if re.fullmatch(r"K\d+", upper) and upper in evidence.refs:
        return {
            "ref": upper,
            "type": "relay",
            "value": "5V relay",
            "manufacturer": "Omron",
            "part_number": "G5Q-14-DC5",
            "footprint": "Relay_THT:Relay_SPDT_Omron-G5Q-1",
            "reason": "BOM-backed isolated relay output.",
            "constraints": ["5V coil", "no direct GPIO drive"],
        }
    return None


def _normalize_net_pin_shorthands(nets: list[dict[str, Any]], refs: set[str]) -> None:
    for net in nets:
        pins = []
        for pin in net.get("pins", []):
            text = str(pin)
            if text in refs and re.fullmatch(r"R\d+", text):
                pins.extend([f"{text}.1", f"{text}.2"])
            else:
                pins.append(text)
        net["pins"] = _dedupe(pins)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _ref_sort_key(ref: str) -> tuple[str, int, str]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref.upper())
    if not match:
        return (ref, 0, ref)
    return (match.group(1), int(match.group(2)), ref)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Normalize AI netlist source evidence against BOM/user prompt.")
    parser.add_argument("--netlist", default="outputs/phase1/AI_NETLIST_V1.json")
    parser.add_argument("--bom", default="BOM.csv")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    target = write_normalized_design_source(
        Path(args.netlist),
        Path(args.bom),
        Path(args.output) if args.output else None,
    )
    print(f"Normalized design source written: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
