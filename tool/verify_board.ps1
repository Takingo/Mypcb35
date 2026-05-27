# Regenerate board from netlist, run real kicad-cli DRC, print violation summary.
# Usage: pwsh tool/verify_board.ps1  [-OutputRoot outputs/kicad_verify]
param(
  [string]$OutputRoot = "outputs\kicad_verify",
  [string]$Netlist    = "outputs\phase1\AI_NETLIST_V1.json"
)
$ErrorActionPreference = "Stop"
$KiCadRoot   = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"
$KiCadCli    = Join-Path $KiCadRoot "kicad-cli.exe"

$env:KICAD_CONFIG_HOME = "C:\Mypcb\.kicad_config"
$env:HOME              = "C:\Mypcb"
$env:USERPROFILE       = "C:\Mypcb"
$env:PYTHONPATH        = "$KiCadRoot\Lib\site-packages;C:\Mypcb"

& $KiCadPython -m engine.kicad_automation_service `
  --netlist $Netlist --output-root $OutputRoot `
  --kicad-cli $KiCadCli --project-root "C:\Mypcb" `
  --export --continue-on-drc-error 2>&1 | Select-Object -Last 4 | Out-Host

$proj = Split-Path -Leaf (Get-ChildItem "$OutputRoot" -Directory | Select-Object -First 1)
$drc  = "$OutputRoot\$proj\manufacturing\drc_report.json"
& $KiCadPython -c @"
import json, collections, sys
d = json.load(open(r'$drc', encoding='utf-8'))
v = d.get('violations') or d.get('items') or []
u = d.get('unconnected_items') or []
print('VIOLATIONS:', len(v), '| UNCONNECTED:', len(u), '| TOTAL:', len(v)+len(u))
c = collections.Counter(x.get('type','?') for x in v)
for k,n in c.most_common(): print(f'{n:5d}  {k}')
if u: print(f'{len(u):5d}  unconnected_items')
"@
