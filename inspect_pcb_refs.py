import pathlib, sys

outputs = pathlib.Path(r'c:\Mypcb\outputs')
pcbs = sorted(outputs.rglob('*.kicad_pcb'), key=lambda f: f.stat().st_mtime, reverse=True)
if not pcbs:
    print('Hic kicad_pcb yok! outputs klasoru:')
    for f in outputs.rglob('*'):
        print(' ', f)
    sys.exit(0)

import datetime
pcb = pcbs[0]
mtime = datetime.datetime.fromtimestamp(pcb.stat().st_mtime)
print(f'Dosya: {pcb}')
print(f'Son degisiklik: {mtime}')
print()

content = pcb.read_text(encoding='utf-8', errors='ignore')
lines = content.splitlines()
targets = {'SK1', 'SK2', 'U1', 'U2'}
results = {}
i = 0
while i < len(lines):
    line = lines[i]
    if '(footprint' in line:
        fp_line = line.strip()
        # Ilerleyerek reference bul
        j = i
        ref_found = None
        while j < min(i+30, len(lines)):
            if '(reference' in lines[j] or '(property "Reference"' in lines[j]:
                parts = lines[j].strip()
                import re
                m = re.search(r'"([A-Z]+[0-9]+)"', parts)
                if m:
                    ref_found = m.group(1)
                    break
            j += 1
        if ref_found and ref_found in targets:
            # fp_line icinde footprint adini bul
            import re
            m2 = re.search(r'\(footprint\s+"([^"]+)"', fp_line)
            fp_name = m2.group(1) if m2 else fp_line[:100]
            results[ref_found] = fp_name
    i += 1

if results:
    print('=== Bulunan Footprintler ===')
    for ref, fp in sorted(results.items()):
        print(f'  {ref:6s} -> {fp}')
else:
    print('Hedef referanslar (SK1, SK2, U1, U2) PCB dosyasinda bulunamadi.')
    print('Ilk 5 footprint:')
    count = 0
    for line in lines:
        if '(footprint' in line and '"' in line:
            print(' ', line.strip()[:120])
            count += 1
            if count >= 5:
                break
