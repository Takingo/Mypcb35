import sys, os, pathlib, json

sys.path.insert(0, r'C:\Program Files\KiCad\10.0\bin\Lib\site-packages')
os.add_dll_directory(r'C:\Program Files\KiCad\10.0\bin')

try:
    import pcbnew
    print('[OK] pcbnew:', pcbnew.Version())
except Exception as e:
    print('[HATA] pcbnew yuklenemedi:', e)
    sys.exit(1)

netlist = json.loads(pathlib.Path(r'c:\Mypcb\outputs\phase1\AI_NETLIST_V1.json').read_bytes())
comps = netlist.get('components', [])
print('[OK] Netlist:', len(comps), 'komponent')

sk_comps = [c for c in comps if str(c.get('ref','')).upper().startswith('SK')]
u1_comps  = [c for c in comps if c.get('ref','') == 'U1']

print()
print('=== SK bilesenleri (soket olmali) ===')
for c in sk_comps:
    ref   = c.get('ref','?')
    val   = c.get('value','?')
    part  = c.get('part_number','?')
    typ   = c.get('type','?')
    print('  ref=' + ref + ' | value=' + val + ' | type=' + typ)
    print('    part_number=' + part)

if not sk_comps:
    print('  [DIKKAT] SK1/SK2 netlistte YOK!')

print()
print('=== U1 ESP32 ===')
for c in u1_comps:
    ref   = c.get('ref','?')
    val   = c.get('value','?')
    part  = c.get('part_number','?')
    notes = str(c.get('notes',''))[:80]
    print('  ref=' + ref + ' | value=' + val)
    print('    part=' + part)
    print('    notes=' + notes)
