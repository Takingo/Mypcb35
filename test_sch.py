import uuid
from typing import Any

def _escape_s_expr(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')

def generate_sch(netlist: dict) -> str:
    components = netlist.get("components", [])
    nets = netlist.get("nets", [])
    
    comp_pins = {c.get("ref", ""): [] for c in components}
    for net in nets:
        net_name = net.get("net", "")
        for pin_str in net.get("pins", []):
            ref, _, pin = pin_str.partition(".")
            if ref in comp_pins:
                comp_pins[ref].append((pin, net_name))

    body = [
        "(kicad_sch (version 20231120) (generator \"OmniCircuit AI\")",
        f"  (uuid \"{uuid.uuid4()}\")",
        "  (paper \"A3\")",
        "  (title_block",
        f"    (title \"{_escape_s_expr(netlist.get('project_name', 'OmniCircuit AI'))}\")",
        "    (comment 1 \"Auto-generated schematic with real symbols and global labels\")",
        "  )",
    ]

    # Generate lib_symbols
    body.append("  (lib_symbols")
    for comp in components:
        ref = comp.get("ref", "")
        if not ref: continue
        pins = comp_pins[ref]
        height = max(10.0, len(pins) * 2.54 + 2.54)
        
        body.append(f"    (symbol \"OmniCircuit:{ref}\" (in_bom yes) (on_board yes)")
        body.append(f"      (property \"Reference\" \"{ref}\" (at 0 {height/2 + 2} 0) (effects (font (size 1.27 1.27))))")
        body.append(f"      (property \"Value\" \"{_escape_s_expr(comp.get('value', ''))}\" (at 0 {height/2 + 4} 0) (effects (font (size 1.27 1.27))))")
        body.append(f"      (symbol \"OmniCircuit:{ref}_0_1\"")
        body.append(f"        (rectangle (start -5 {height/2}) (end 5 {-height/2}) (stroke (width 0.254) (type default)) (fill (type background)))")
        
        for i, (pin_name, _) in enumerate(pins):
            y_pos = (height/2) - 2.54 - (i * 2.54)
            # Pin on the left side
            body.append(f"        (pin passive line (at -7.54 {y_pos} 0) (length 2.54)")
            body.append(f"          (name \"{pin_name}\" (effects (font (size 1.27 1.27))))")
            body.append(f"          (number \"{pin_name}\" (effects (font (size 1.27 1.27))))")
            body.append(f"        )")
            
        body.append("      )")
        body.append("    )")
    body.append("  )")

    # Place instances and global labels
    x_start = 30.0
    y_start = 30.0
    
    for idx, comp in enumerate(components):
        ref = comp.get("ref", "")
        if not ref: continue
        
        x = x_start + (idx % 4) * 60.0
        y = y_start + (idx // 4) * 60.0
        
        body.append(f"  (symbol (lib_id \"OmniCircuit:{ref}\") (at {x} {y} 0) (unit 1)")
        body.append(f"    (in_bom yes) (on_board yes)")
        body.append(f"    (uuid \"{uuid.uuid4()}\")")
        body.append(f"    (property \"Reference\" \"{ref}\" (at {x} {y-10} 0))")
        body.append(f"    (property \"Value\" \"{_escape_s_expr(comp.get('value', ''))}\" (at {x} {y-12} 0))")
        body.append("  )")

        # Global labels
        pins = comp_pins[ref]
        height = max(10.0, len(pins) * 2.54 + 2.54)
        for i, (pin_name, net_name) in enumerate(pins):
            if not net_name: continue
            y_pos = y - (height/2) + 2.54 + (i * 2.54)
            pin_x = x - 7.54
            
            # Place global label
            body.append(f"  (global_label \"{net_name}\" (shape input) (at {pin_x} {y_pos} 180)")
            body.append(f"    (effects (font (size 1.27 1.27)) (justify right))")
            body.append(f"    (uuid \"{uuid.uuid4()}\")")
            body.append(f"  )")

    body.append(")")
    return "\n".join(body)

if __name__ == "__main__":
    import json
    with open("c:/Mypcb/outputs/phase1/AI_NETLIST_V1.example.json") as f:
        data = json.loads(f.read())
    sch = generate_sch(data)
    with open("test_out.kicad_sch", "w") as f:
        f.write(sch)
