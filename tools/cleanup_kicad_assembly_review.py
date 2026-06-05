from __future__ import annotations

import uuid
from pathlib import Path


PCB_PATH = Path(
    "outputs/kicad/esp32_s3_dwm3000_uwb_anchor_with_relay_outputs/"
    "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
)


REMOVE_UUIDS = {
    # RV1 silkscreen over copper / overlap with C24
    "2c51dcfa-2034-4e4e-8bbb-42030915e5ab",
    "cbce4065-cef7-4116-8d32-d8005052f901",
    "0a6d0b28-89cf-4603-b4c0-0f81af4c8e35",
    # U3/J1 silkscreen edge and mutual overlaps
    "57805b66-e189-42ad-91bc-cc23ed2a2a01",
    "626cc8db-d5a5-4e80-a35a-6f22058d5cd1",
    "c55ae0bb-4c98-4dd0-9b27-1f1588c6a3cf",
    "88a83428-5190-49c1-9e60-c4f3e18bfdcf",
    "22c34be2-ae5e-4271-9fb7-d95678d1719e",
    "3682a9fa-eb5a-4a3c-ba68-06d10c08c03a",
    "1f86794d-2dd7-4e2e-8b18-fb3de9277c90",
    "7996a7f9-bb28-4f8e-9f6e-14709434b7f7",
    "1d7a05fb-5db6-4ac6-bdad-2a4305175bac",
    "67b8fb25-6347-4ac0-8ea0-271347d028ef",
    # C24 silkscreen overlap with RV1
    "2d3f4827-cc8a-4e95-8713-b7b178a65f8b",
    "c287fdaa-166c-49b6-8dda-98fd253e3288",
    # Over-aggressive assembly courtyards for sockets / AC area / varistor.
    "d98a06cb-1a49-49fd-b695-c8d885c7759d",
    "28e046fb-d953-4944-b293-ea876e7eb090",
    "c5c0bb95-73af-4b1e-9e37-10d024046fcf",
    "d453f87a-c2cb-4ac6-a2e2-b2c2fcb9972c",
    "ea887fb9-5fc4-4913-940b-7d38bcf1122d",
    "8436d498-223c-41ac-9b52-37b17be88b1b",
    "ead419c9-f064-4315-a5bf-cb6c1bfcf9ef",
    "02f21902-9df9-4571-948d-6fd01a0b8dd8",
    "9d38a179-d23b-44dc-b449-fd4d2c904e31",
    "0cdd4826-0666-4bec-8ee7-2ab9a66ad256",
    "8f917415-d79b-498d-a633-9c5b4cebeecd",
    "5be78070-131f-4dbc-8b33-f417dad78602",
    "fb31fbb2-77eb-440a-9ada-cb057b12f559",
    "bdd5cdab-f5a4-4dc2-8322-7a285b9cdcd7",
}


FOOTPRINT_DRAWING_PREFIXES = (
    "(fp_line",
    "(fp_rect",
    "(fp_poly",
    "(fp_circle",
    "(fp_arc",
    "(fp_text",
)

ASSEMBLY_REVIEW_LAYERS = ('(layer "F.SilkS")', '(layer "F.CrtYd")')
REPAIR_MARKER = "codex-repair-5v-iso-link"
TRACK_PREFIXES = ("(segment", "(via")
LOCAL_DANGLING_5V_BRANCH_UUIDS = {
    "65a8b783-5c35-479b-b936-9d9ad6cdf3ca",
    "70182cf9-aec6-4d80-bc17-0aa0a251747c",
    "726ef516-6aa4-4c00-bc10-1867c00157bf",
    "d16d30d3-2107-40dd-8bf1-eda9fad06f14",
    "e4355208-8926-41c3-959c-4970507c381e",
}


def paren_delta(line: str) -> int:
    in_string = False
    escaped = False
    delta = 0
    for ch in line:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_string:
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "(":
            delta += 1
        elif ch == ")":
            delta -= 1
    return delta


def expression_start(lines: list[str], uuid_line: int) -> int:
    for idx in range(uuid_line, -1, -1):
        stripped = lines[idx].lstrip()
        if stripped.startswith(FOOTPRINT_DRAWING_PREFIXES):
            return idx
    raise ValueError(f"Could not find fp expression start for line {uuid_line + 1}")


def expression_end(lines: list[str], start: int) -> int:
    depth = 0
    for idx in range(start, len(lines)):
        depth += paren_delta(lines[idx])
        if depth == 0:
            return idx
    raise ValueError(f"Could not find fp expression end for line {start + 1}")


def drawing_ranges_on_assembly_layers(lines: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].lstrip()
        if not stripped.startswith(FOOTPRINT_DRAWING_PREFIXES):
            idx += 1
            continue

        end = expression_end(lines, idx)
        expression = "".join(lines[idx : end + 1])
        if any(layer in expression for layer in ASSEMBLY_REVIEW_LAYERS):
            ranges.append((idx, end))
        idx = end + 1
    return ranges


def repair_marker_ranges(lines: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].lstrip()
        if not stripped.startswith(TRACK_PREFIXES):
            idx += 1
            continue

        end = expression_end(lines, idx)
        expression = "".join(lines[idx : end + 1])
        if REPAIR_MARKER in expression:
            ranges.append((idx, end))
        idx = end + 1
    return ranges


def legacy_repair_ranges(lines: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    idx = 0
    while idx < len(lines):
        stripped = lines[idx].lstrip()
        if not stripped.startswith(TRACK_PREFIXES):
            idx += 1
            continue

        end = expression_end(lines, idx)
        expression = "".join(lines[idx : end + 1])
        is_old_segment = (
            "(start 45.8846 9.9808)" in expression
            and "(end 50.5 15.6)" in expression
            and '(net "+5V_ISO")' in expression
        )
        is_old_via = "(at 50.5 15.6)" in expression and '(net "+5V_ISO")' in expression
        is_endpoint_via = "(at 45.8846 9.9808)" in expression and '(net "+5V_ISO")' in expression
        is_route_segment = (
            '(net "+5V_ISO")' in expression
            and any(
                token in expression
                for token in (
                    "(end 45.8846 8.2)",
                    "(start 45.8846 8.2)",
                    "(start 39.5 8.2)",
                    "(start 39.5 13.5)",
                    "(start 50.5 13.5)",
                    "(end 45.8846 7.6)",
                    "(start 45.8846 7.6)",
                    "(start 61 7.6)",
                    "(start 61 13.5)",
                    "(end 47.525 7.365)",
                    "(end 47.2304 8.635)",
                    "(start 47.2304 8.635)",
                    "(end 43.0308 9.9808)",
                    "(start 43.0308 9.9808)",
                    "(start 47.525 8.635)",
                    "(start 59 8.635)",
                    "(start 59 15.6)",
                    "(end 47.525 8.0)",
                    "(start 47.525 8.0)",
                    "(start 40.0 8.0)",
                    "(start 40.0 13.2)",
                    "(start 50.5 13.2)",
                    "(end 47.525 7.3)",
                    "(start 47.525 7.3)",
                    "(start 39.85 7.3)",
                    "(start 39.85 13.45)",
                    "(start 50.5 13.45)",
                    "(end 47.525 7.875)",
                    "(start 47.525 7.875)",
                    "(start 39.75 7.875)",
                    "(start 39.75 13.45)",
                    "(end 46.3 8.635)",
                    "(start 46.3 8.635)",
                    "(start 46.3 6.2)",
                    "(start 37.2 6.2)",
                    "(start 37.2 13.45)",
                )
            )
        )
        is_u4_repair_via = "(at 47.525 8.635)" in expression and '(net "+5V_ISO")' in expression
        is_local_dangling_branch = any(branch_uuid in expression for branch_uuid in LOCAL_DANGLING_5V_BRANCH_UUIDS)
        if is_old_segment or is_old_via or is_endpoint_via or is_route_segment or is_u4_repair_via or is_local_dangling_branch:
            ranges.append((idx, end))
        idx = end + 1
    return ranges


def add_5v_iso_repair(lines: list[str]) -> tuple[list[str], bool]:
    text = "".join(lines)
    if "(at 47.525 8.635)" in text and '(layer "In2.Cu")' in text and "(end 50.5 15.6)" in text:
        return lines, False

    insert_at = None
    for idx, line in enumerate(lines):
        if line.lstrip().strip() == "(zone":
            insert_at = idx
            break

    if insert_at is None:
        for idx in range(len(lines) - 1, -1, -1):
            if lines[idx].lstrip().startswith((")",)):
                insert_at = idx
                break

    if insert_at is None:
        raise ValueError("Could not find insertion point for +5V_ISO repair")

    f_cu_points = [
        ("47.525 8.635", "47.525 7.365"),
        ("47.525 8.635", "47.2304 8.635"),
        ("47.2304 8.635", "45.8846 9.9808"),
        ("45.8846 9.9808", "43.0308 9.9808"),
        ("43.0308 9.9808", "42.05 9"),
    ]
    repair_points = f_cu_points
    repair: list[str] = []
    for start, end in repair_points:
        repair.extend(
            [
                "\t(segment\n",
                f"\t\t(start {start})\n",
                f"\t\t(end {end})\n",
                "\t\t(width 0.2)\n",
                '\t\t(layer "F.Cu")\n',
                '\t\t(net "+5V_ISO")\n',
                f'\t\t(uuid "{uuid.uuid4()}")\n',
                "\t)\n",
            ]
        )
    repair.extend(
        [
            "\t(via\n",
            "\t\t(at 47.525 8.635)\n",
            "\t\t(size 0.45)\n",
            "\t\t(drill 0.2)\n",
            '\t\t(layers "F.Cu" "B.Cu")\n',
            '\t\t(net "+5V_ISO")\n',
            f'\t\t(uuid "{uuid.uuid4()}")\n',
            "\t)\n",
            "\t(segment\n",
            "\t\t(start 47.525 8.635)\n",
            "\t\t(end 50.5 15.6)\n",
            "\t\t(width 0.2)\n",
            '\t\t(layer "In2.Cu")\n',
            '\t\t(net "+5V_ISO")\n',
            f'\t\t(uuid "{uuid.uuid4()}")\n',
            "\t)\n",
        ]
    )
    return lines[:insert_at] + repair + lines[insert_at:], True


def main() -> None:
    lines = PCB_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    ranges: list[tuple[int, int]] = drawing_ranges_on_assembly_layers(lines)
    ranges.extend(repair_marker_ranges(lines))
    ranges.extend(legacy_repair_ranges(lines))

    for idx, line in enumerate(lines):
        if "(uuid " not in line:
            continue
        if any(uuid in line for uuid in REMOVE_UUIDS):
            start = expression_start(lines, idx)
            end = expression_end(lines, start)
            ranges.append((start, end))

    ranges = sorted(set(ranges))
    out: list[str] = []
    cursor = 0
    for start, end in ranges:
        out.extend(lines[cursor:start])
        cursor = end + 1
    out.extend(lines[cursor:])

    out = [line.replace("(vias not_allowed)", "(vias allowed)") for line in out]
    out, repaired_5v_iso = add_5v_iso_repair(out)

    PCB_PATH.write_text("".join(out), encoding="utf-8")
    print(
        f"Removed {len(ranges)} assembly-review drawing/text objects from {PCB_PATH}; "
        f"+5V_ISO repair added: {repaired_5v_iso}"
    )


if __name__ == "__main__":
    main()
