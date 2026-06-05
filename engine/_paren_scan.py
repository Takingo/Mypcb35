"""Locate paren imbalance in corrupted .kicad_pcb file."""
import sys

PCB = sys.argv[1] if len(sys.argv) > 1 else r"C:\Mypcb\outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb"
text = open(PCB, "r", encoding="utf-8").read()

depth = 0
in_string = False
escape = False
line = 1
col = 0
neg_dives = []
max_depth = 0
ESC = chr(92)
QUOTE = chr(34)

for i, ch in enumerate(text):
    col += 1
    if ch == "\n":
        line += 1
        col = 0
        continue
    if escape:
        escape = False
        continue
    if ch == ESC and in_string:
        escape = True
        continue
    if ch == QUOTE:
        in_string = not in_string
        continue
    if in_string:
        continue
    if ch == "(":
        depth += 1
        if depth > max_depth:
            max_depth = depth
    elif ch == ")":
        depth -= 1
        if depth < 0:
            neg_dives.append((line, col, i))

print(f"Final depth (0 = balanced): {depth}")
print(f"Max depth reached: {max_depth}")
print(f"Number of points where depth went < 0: {len(neg_dives)}")
for ln, cl, idx in neg_dives[:15]:
    snip = text[max(0, idx-80):min(len(text), idx+40)].replace("\n", " | ")
    print(f"  line {ln} col {cl}:  ...{snip}...")
