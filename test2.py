import uuid
import sys
def write_test(file_path):
    body = [
        "(kicad_sch (version 20231120) (generator \"OmniCircuit AI\")",
        f"  (uuid \"{uuid.uuid4()}\")",
        "  (paper \"A3\")",
        "  (text_box",
        "    \"U1: ESP32\"",
        "    (at 50 50 0)",
        "    (size 20 20)",
        "    (stroke (width 0.1) (type solid))",
        "    (fill (type none))",
        "  )",
        "  (global_label \"NET_VCC\" (shape input) (at 30 50 180)",
        "    (effects (font (size 1.27 1.27)) (justify right))",
        f"    (uuid \"{uuid.uuid4()}\")",
        "  )",
        "  (wire (pts (xy 30 50) (xy 50 50))",
        "    (stroke (width 0) (type default))",
        f"    (uuid \"{uuid.uuid4()}\")",
        "  )",
        ")"
    ]
    with open(file_path, "w") as f:
        f.write("\n".join(body))

write_test("test2.kicad_sch")
