import pathlib

path = pathlib.Path(r'c:\Mypcb\engine\kicad_automation_service.py')
text = path.read_text(encoding='utf-8')

# 1. Add utf-8 fix at the top
if 'sys.stdout = io.TextIOWrapper' not in text:
    text = text.replace('import sys\nimport traceback\n', 'import sys\nimport traceback\nimport io\nsys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding=\'utf-8\')\n')

# 2. Add the custom footprints and logic
methods = '''
    def _build_esp32_devkit(self, pcbnew: Any, board: Any) -> Any:
        fp = pcbnew.FOOTPRINT(board)
        self._set_synthetic_fpid(pcbnew, fp, "ESP32_DevKit")
        
        left_pads = ["2", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "38", "NC_46", "37", "36", "35", "34", "33", "32"]
        right_pads = ["NC_5V", "1", "16", "15", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "27", "28", "29", "30", "31", "1", "1", "1"]
        
        for i, pad_name in enumerate(left_pads):
            pad = pcbnew.PAD(fp)
            pad.SetName(pad_name)
            pad.SetNumber(pad_name)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE if i > 0 else pcbnew.PAD_SHAPE_RECT)
            pad.SetSize(self._vector(pcbnew, 1.7, 1.7))
            pad.SetDrillSize(self._vector(pcbnew, 1.0, 1.0))
            pad.SetLayerSet(pcbnew.LSET.AllCuMask())
            pad.SetPosition(self._vector(pcbnew, -12.7, i * 2.54))
            fp.Add(pad)

        for i, pad_name in enumerate(right_pads):
            pad = pcbnew.PAD(fp)
            pad.SetName(pad_name)
            pad.SetNumber(pad_name)
            pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
            pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
            pad.SetSize(self._vector(pcbnew, 1.7, 1.7))
            pad.SetDrillSize(self._vector(pcbnew, 1.0, 1.0))
            pad.SetLayerSet(pcbnew.LSET.AllCuMask())
            pad.SetPosition(self._vector(pcbnew, 12.7, i * 2.54))
            fp.Add(pad)

        return fp

    def _build_empty(self, pcbnew: Any, board: Any) -> Any:
        fp = pcbnew.FOOTPRINT(board)
        self._set_synthetic_fpid(pcbnew, fp, "Empty")
        return fp

    def _build_generic_tht_2pin'''

if 'def _build_esp32_devkit' not in text:
    text = text.replace('    def _build_generic_tht_2pin', methods)

find_str = '        comp_type  = component.get("type", "")'
replace_str = find_str + '''
        notes = component.get("notes", "")

        if ref in ("SK1", "SK2"):
            print(f"[FP] {ref}: DevKit U1 uzerine binecegi icin bos footprint ataniyor", flush=True)
            return self._build_empty(pcbnew, board)

        is_socket_note = "SOKET" in notes.upper() or "SOCKET" in notes.upper() or "SOKET" in part_number.upper() or "SOCKET" in part_number.upper()
        if is_socket_note and comp_type in ("mcu", "rf_module", "wifi+ble mcu module", "wifi module"):
            print(f"[FP] {ref}: SOKET talebi -> ESP32_DevKit ozel footprint uretiliyor", flush=True)
            return self._build_esp32_devkit(pcbnew, board)
'''
if 'if ref in ("SK1", "SK2"):' not in text:
    text = text.replace(find_str, replace_str)

path.write_text(text, encoding='utf-8')
print('Success')
