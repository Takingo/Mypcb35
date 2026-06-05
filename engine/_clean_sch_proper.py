"""Properly remove C99/C100/C101/C102 from .kicad_sch via S-expression block scan.

Approach: tokenize the file at the paren level, find every (symbol ...) block at depth 1
(top-level inside kicad_sch) and at depth 2 (inside lib_symbols). If the block's text
contains the ghost reference, remove the entire balanced block.
"""
import re
import sys

SCH = r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_sch"
GHOSTS = {"C99", "C100", "C101", "C102"}

text = open(SCH, "r", encoding="utf-8").read()
print(f"[INFO] Before: {len(text)} chars, paren balance = {text.count('(') - text.count(')')}")


def find_balanced_end(s, open_idx):
    """Given index of `(`, return inclusive index of matching `)`."""
    depth = 0
    in_str = False
    escape = False
    i = open_idx
    while i < len(s):
        ch = s[i]
        if escape:
            escape = False
        elif ch == "\\" and in_str:
            escape = True
        elif ch == '"':
            in_str = not in_str
        elif not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def remove_ghost_blocks(text, marker_re):
    """Find every `(symbol ...)` open paren, check the next ~200 chars or so against
    marker_re. If the marker is inside the balanced block, snip it."""
    out = []
    i = 0
    n = len(text)
    in_str = False
    escape = False
    removed = 0
    while i < n:
        ch = text[i]
        if escape:
            escape = False
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and in_str:
            escape = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            i += 1
            continue
        if not in_str and ch == "(":
            # Peek ahead: is this `(symbol`?
            ahead = text[i:i + 8]
            if ahead.startswith("(symbol") and (len(ahead) == 7 or ahead[7] in " \t\n"):
                end = find_balanced_end(text, i)
                if end < 0:
                    # broken; abort safely
                    out.append(ch)
                    i += 1
                    continue
                block = text[i:end + 1]
                if marker_re.search(block):
                    # remove this block; also eat preceding spaces/tabs and one newline
                    while out and out[-1] in " \t":
                        out.pop()
                    if out and out[-1] == "\n":
                        out.pop()
                    i = end + 1
                    removed += 1
                    continue
        out.append(ch)
        i += 1
    return "".join(out), removed


# Build marker regex matching any of the ghost references in either form:
#   "OmniCircuit:C99"   (lib_symbols id)
#   (property "Reference" "C99" ...)
ghost_alt = "|".join(re.escape(g) for g in GHOSTS)
marker = re.compile(rf'"OmniCircuit:({ghost_alt})"|\(property\s+"Reference"\s+"({ghost_alt})"')

# Iterate removal until stable (handles nested cases)
prev_text = None
total_removed = 0
while prev_text != text:
    prev_text = text
    text, n = remove_ghost_blocks(text, marker)
    total_removed += n

print(f"[INFO] Removed {total_removed} (symbol ...) blocks total.")

balance = text.count("(") - text.count(")")
remaining = sorted(set(re.findall(r'"Reference"\s+"(C\d+)"', text)), key=lambda s: int(s[1:]))
ghosts_left = [g for g in GHOSTS if g in remaining]
print(f"[INFO] After:  {len(text)} chars, paren balance = {balance}")
print(f"[INFO] C-refs remaining: {remaining}")
print(f"[INFO] Ghosts left:      {ghosts_left}")

if balance != 0:
    print("[FATAL] paren imbalance, refusing to write")
    sys.exit(1)
if ghosts_left:
    print("[FATAL] ghosts not fully removed")
    sys.exit(2)

open(SCH, "w", encoding="utf-8").write(text)
print("[OK] Schematic written.")
