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
                token = (row.get("Reference") or row.get("Referans") or "").strip()
                if not token:
                    continue
                meta = {
                    "value": (row.get("Value") or row.get("Deger") or "").strip(),
                    "manufacturer": (row.get("Manufacturer") or row.get("Uretici") or "").strip(),
                    "part_number": (row.get("Part Number") or row.get("Parca Numarasi") or "").strip(),
                    "package_footprint": (row.get("Package / Footprint") or row.get("Footprint") or row.get("Package") or "").strip(),
                    "placement": (row.get("Critical Placement Distance") or row.get("Placement") or "").strip(),
                    "notes": (row.get("Notes") or row.get("Description") or row.get("Notlar") or row.get("Aciklama") or "").strip(),
                }
                if _is_bom_section_header(token):
                    continue
                for ref in _expand_ref_list(token.upper()):
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
    _apply_socketed_module_rules(components, nets, evidence)
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
    match = re.fullmatch(r"([A-Z_]+)(\d+)-(?:(?:[A-Z_]+)?)(\d+)", token)
    if not match:
        return {token}
    prefix, start, end = match.groups()
    start_i = int(start)
    end_i = int(end)
    if end_i < start_i or end_i - start_i > 200:
        return {token}
    return {f"{prefix}{index}" for index in range(start_i, end_i + 1)}


def _expand_ref_list(token: str) -> set[str]:
    refs: set[str] = set()
    normalized = token.replace("–", "-").replace("—", "-")
    for part in re.split(r"[,;\s]+", normalized):
        part = part.strip()
        if not part:
            continue
        refs.update(_expand_ref_token(part))
    return refs


def _is_bom_section_header(token: str) -> bool:
    text = token.strip()
    return text.startswith("==") and text.endswith("==")


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
        for field in ("value", "manufacturer", "part_number", "notes"):
            bom_val = (meta.get(field) or "").strip()
            if bom_val and str(component.get(field, "")).strip().lower() != bom_val.lower():
                component[field] = bom_val
        for field in ("package_footprint", "placement"):
            bom_val = (meta.get(field) or "").strip()
            if bom_val:
                component[field] = bom_val
        if not str(component.get("footprint", "")).strip():
            footprint = _footprint_from_package_meta(meta.get("package_footprint", ""), ref)
            if footprint:
                component["footprint"] = footprint


def _apply_socketed_module_rules(
    components: list[dict[str, Any]],
    nets: list[dict[str, Any]],
    evidence: BomEvidence,
) -> None:
    """Honor BOM instructions such as:
    U1 = module plugs into SK1+SK2, NOT soldered to PCB directly.

    U1 remains in the source model/BOM, but it is not a PCB-mounted footprint.
    Electrical pins are rewired to the two 1x22 female socket footprints.
    """
    for component in components:
        ref = str(component.get("ref", "")).strip().upper()
        if ref in {"SK1", "SK2"}:
            component["type"] = "socket"
            component["footprint"] = "Connector_PinSocket_2.54mm:PinSocket_1x22_P2.54mm_Vertical"
            constraints = list(component.get("constraints") or [])
            if "2.54mm pitch 1x22 female socket" not in constraints:
                constraints.append("2.54mm pitch 1x22 female socket")
            component["constraints"] = constraints
        if ref != "U1":
            continue
        meta = evidence.ref_meta.get(ref, {})
        text = " ".join(
            str(meta.get(key, "")) for key in ("package_footprint", "placement", "notes")
        ).lower()
        if not (
            ("sk1" in text and "sk2" in text)
            or "not soldered" in text
            or "plugs into" in text
        ):
            continue
        component["type"] = "virtual_module"
        component["footprint"] = "not_pcb_mounted"
        component["not_pcb_mounted"] = True
        constraints = list(component.get("constraints") or [])
        for item in (
            "PCB footprint must be SK1+SK2 female sockets, not U1 solder pads",
            "GPIO33/GPIO34/GPIO35/GPIO36/GPIO37 are PSRAM-reserved and must remain NC",
        ):
            if item not in constraints:
                constraints.append(item)
        component["constraints"] = constraints
        component["reason"] = (
            str(component.get("reason", "")).strip()
            + " BOM states U1 plugs into SK1+SK2 sockets and is not soldered directly."
        ).strip()

    for net in nets:
        rewritten: list[str] = []
        for pin in net.get("pins", []):
            text = str(pin)
            mapped = _map_u1_pin_to_socket_pin(text)
            if mapped is None:
                mapped = _map_socket_alias_pin(text)
            if mapped == "__DROP_RESERVED__":
                continue
            rewritten.append(mapped or text)
        net["pins"] = _dedupe(rewritten)


_ESP32_SOCKET_ALIAS_TO_PAD = {
    "GND": 1,
    "3V3": 2,
    "EN": 3,
    "GPIO4": 4,
    "GPIO5": 5,
    "GPIO6": 6,
    "GPIO7": 7,
    "GPIO15": 8,
    "GPIO16": 9,
    "GPIO17": 10,
    "GPIO18": 11,
    "GPIO8": 12,
    "GPIO19": 13,
    "GPIO20": 14,
    "U0RXD": 15,
    "RXD0": 15,
    "GPIO44": 15,
    "U0TXD": 16,
    "TXD0": 16,
    "GPIO43": 16,
    "GPIO1": 17,
    "GPIO2": 18,
    "GPIO42": 19,
    "GPIO41": 20,
    "GPIO40": 21,
    "GPIO39": 22,
    "GPIO38": 23,
    "GPIO37": 24,
    "GPIO36": 25,
    "GPIO35": 26,
    "GPIO0": 27,
    "GPIO45": 28,
    "GPIO48": 29,
    "GPIO47": 30,
    "GPIO21": 31,
    "GPIO14": 32,
    "GPIO13": 33,
    "GPIO12": 34,
    "GPIO11": 35,
    "GPIO10": 36,
    "GPIO9": 37,
    "GPIO3": 38,
    "GND2": 39,
    "GND3": 40,
    "SPI_CS": 36,
    "SPI_MOSI": 35,
    "SPI_CLK": 34,
    "SPI_MISO": 33,
    "IRQ": 32,
    "EXT_TX": 8,
}


def _map_u1_pin_to_socket_pin(pin: str) -> str | None:
    if not pin.startswith("U1."):
        return None
    raw = pin.split(".", 1)[1].strip().upper()
    if raw in {"GPIO33", "GPIO34", "GPIO35", "GPIO36", "GPIO37"}:
        return "__DROP_RESERVED__"
    pad: int | None
    if raw.isdigit():
        pad = int(raw)
    else:
        pad = _ESP32_SOCKET_ALIAS_TO_PAD.get(raw)
    if pad is None:
        return None
    if pad <= 22:
        return f"SK1.{pad}"
    return f"SK2.{pad - 22}"


def _map_socket_alias_pin(pin: str) -> str | None:
    ref, dot, raw_pin = pin.partition(".")
    if dot != "." or ref not in {"SK1", "SK2"}:
        return None
    raw = raw_pin.upper()
    for prefix in ("PIN_", "PIN", "PAD_", "PAD"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    if raw in {"GPIO33", "GPIO34", "GPIO35", "GPIO36", "GPIO37"}:
        return "__DROP_RESERVED__"
    if raw.isdigit() and 1 <= int(raw) <= 22:
        return f"{ref}.{int(raw)}"
    return _map_u1_pin_to_socket_pin(f"U1.{raw}")


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
    refs = {str(component.get("ref", "")).strip() for component in components}
    net_refs = _net_refs(nets)
    
    refs = {str(component.get("ref", "")).strip() for component in components}
    
    # Adim 1: AI tarafindan uydurulmus ama BOM'da (evidence'ta) asla olmayan
    # 'K36' veya 'OK36' gibi sacma bilesenleri temizle.
    evidence_valid_refs = evidence.refs | set(evidence.ref_meta.keys())
    
    filtered_components = []
    hallucinated_refs = set()
    for c in components:
        cref = str(c.get("ref", "")).strip()
        if cref in evidence_valid_refs:
            filtered_components.append(c)
        else:
            # Sadece eger standart bir prefix ise ve BOM'da yoksa sil (orn: K3, OK5, Q12)
            if re.fullmatch(r"[A-Z]+\d+", cref) or _looks_like_component_ref(cref):
                print(f"Normalizer: AI hallucination removed: {cref}")
                hallucinated_refs.add(cref)
            else:
                filtered_components.append(c) # Jumper vs olabilir
    components.clear()
    components.extend(filtered_components)

    # Hallucinated bilesenlerin net baglantilarini da temizle
    for net in nets:
        original_pins = net.get("pins", [])
        new_pins = []
        for p in original_pins:
            if isinstance(p, str):
                if ":" in p:
                    pref = p.split(":")[0].strip()
                elif "." in p:
                    pref = p.split(".")[0].strip()
                else:
                    pref = p.strip()
                    
                if pref not in hallucinated_refs:
                    new_pins.append(p)
            elif isinstance(p, dict):
                pref = str(p.get("ref", "")).strip()
                if pref not in hallucinated_refs:
                    new_pins.append(p)
            else:
                new_pins.append(p)
        net["pins"] = new_pins

    # Adim 2: BOM'da olup da AI'in unuttugu (orn. SK1, SK2) bilesenleri zorla ekle
    refs = {str(component.get("ref", "")).strip() for component in components}
    net_refs = _net_refs(nets)
    valid_refs = net_refs | evidence_valid_refs
    all_refs_to_add = sorted(valid_refs - refs, key=_ref_sort_key)
    for ref in all_refs_to_add:
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
    # K\d+ — role
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
    # SK\d+ — dişi soket (BOM'dan gelen her SK ref)
    if re.fullmatch(r"SK\d+", upper):
        meta = evidence.ref_meta.get(upper, {})
        val  = meta.get("value") or "Female_Header_1x22_2.54mm"
        part = meta.get("part_number") or "61302211821"
        mfr  = meta.get("manufacturer") or "Samtec"
        notes = meta.get("notes") or "2.54mm pitch disi soket; ESP32 modulu soketin uzerine takilir"
        # Coklu part number'dan ilkini al
        for sep in (" veya ", " or ", " / ", "/"):
            if sep in part:
                part = part.split(sep)[0].strip()
                break
        return {
            "ref": upper,
            "type": "socket",
            "value": val,
            "manufacturer": mfr,
            "part_number": part,
            "footprint": "Connector_PinSocket_2.54mm:PinSocket_1x22_P2.54mm_Vertical",
            "reason": "BOM-backed 22-pin female socket for ESP32 module (socketed installation).",
            "constraints": ["2.54mm pitch", "THT"],
            "notes": notes,
        }
    # Genel BOM meta ile örtüşen ref — tip çıkarimi yap
    meta = evidence.ref_meta.get(upper)
    if meta and meta.get("part_number"):
        val   = meta.get("value") or ""
        part  = meta.get("part_number") or ""
        mfr   = meta.get("manufacturer") or "Generic"
        notes = meta.get("notes") or ""
        # part number coklu ise ilkini al
        for sep in (" veya ", " or ", " / ", "/"):
            if sep in part:
                part = part.split(sep)[0].strip()
                break
        # Basit tip tahmini
        pu = part.upper()
        if re.fullmatch(r"C\d+", upper): typ = "capacitor"
        elif re.fullmatch(r"R\d+", upper): typ = "resistor"
        elif re.fullmatch(r"R_[A-Z]+\d+", upper): typ = "resistor"
        elif re.fullmatch(r"L\d+", upper): typ = "inductor"
        elif re.fullmatch(r"D\d+", upper): typ = "diode"
        elif re.fullmatch(r"Q\d+", upper): typ = "n_mosfet"
        elif re.fullmatch(r"U\d+", upper): typ = "ic"
        elif re.fullmatch(r"J\d+", upper): typ = "connector"
        elif re.fullmatch(r"FB\d+", upper): typ = "ferrite_bead"
        elif re.fullmatch(r"LED\d+", upper): typ = "led"
        elif re.fullmatch(r"SW\d+", upper): typ = "switch"
        elif re.fullmatch(r"BAT\d+", upper): typ = "battery"
        elif re.fullmatch(r"TP\d+", upper): typ = "test_point"
        elif re.fullmatch(r"ANT\d+", upper): typ = "antenna"
        elif re.fullmatch(r"X\d+", upper): typ = "crystal"
        elif re.fullmatch(r"RV\d+", upper): typ = "varistor"
        elif re.fullmatch(r"F\d+", upper): typ = "fuse"
        elif re.fullmatch(r"SK\d+", upper): typ = "socket"
        else: typ = "component"
        return {
            "ref": upper,
            "type": typ,
            "value": val,
            "manufacturer": mfr,
            "part_number": part,
            "footprint": _footprint_from_package_meta(meta.get("package_footprint", ""), upper),
            "reason": "BOM-backed component (ref_meta).",
            "constraints": [],
            "notes": notes,
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


def _looks_like_component_ref(ref: str) -> bool:
    upper = ref.upper()
    if not any(char.isdigit() for char in upper):
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9_-]*", upper))


def _footprint_from_package_meta(package: str, ref: str) -> str:
    text = package.strip().upper()
    upper = ref.upper()
    if not text:
        return ""
    if "SOT-23-6" in text:
        return "Package_TO_SOT_SMD:SOT-23-6"
    if text in {"SO-8", "SOIC-8"} or "SO-8" in text:
        return "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    if "LQFP-48" in text:
        return "Package_QFP:LQFP-48_7x7mm_P0.5mm"
    if "0805" in text and (re.fullmatch(r"R\d+", upper) or re.fullmatch(r"R_[A-Z]+\d+", upper)):
        return "Resistor_SMD:R_0805_2012Metric"
    if "0805" in text and re.fullmatch(r"C\d+", upper):
        return "Capacitor_SMD:C_0805_2012Metric"
    return package.strip()


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
