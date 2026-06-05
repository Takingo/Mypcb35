import pathlib

path = pathlib.Path(r'c:\Mypcb\engine\kicad_automation_service.py')
text = path.read_text(encoding='utf-8')

find_str = '''    def _build_empty(self, pcbnew: Any, board: Any) -> Any:
        fp = pcbnew.FOOTPRINT(board)
        self._set_synthetic_fpid(pcbnew, fp, "Empty")
        return fp'''

replace_str = '''    def _build_empty(self, pcbnew: Any, board: Any) -> Any:
        fp = pcbnew.FOOTPRINT(board)
        self._set_synthetic_fpid(pcbnew, fp, "Empty")
        # Add a single dummy 0.1mm SMD pad so it doesn't fail DRC 0-pad check
        pad = pcbnew.PAD(fp)
        pad.SetName("1")
        pad.SetNumber("1")
        pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        pad.SetShape(pcbnew.PAD_SHAPE_RECT)
        pad.SetSize(self._vector(pcbnew, 0.1, 0.1))
        pad.SetLayerSet(pcbnew.LSET.FrontMask())
        pad.SetPosition(self._vector(pcbnew, 0, 0))
        fp.Add(pad)
        return fp'''

if 'dummy 0.1mm SMD pad' not in text:
    text = text.replace(find_str, replace_str)
    path.write_text(text, encoding='utf-8')
    print('Success')
