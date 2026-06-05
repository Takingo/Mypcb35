import pathlib
import sys

path = pathlib.Path(r'c:\Mypcb\engine\kicad_automation_service.py')
text = path.read_text(encoding='utf-8')

# 1. Add utf-8 fix at the top and path fix
if 'sys.stdout = io.TextIOWrapper' not in text:
    text = text.replace('import sys\nimport traceback\n', 'import sys\nimport os\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nimport traceback\nimport io\nsys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding=\'utf-8\')\n')

path.write_text(text, encoding='utf-8')
print('Success')
