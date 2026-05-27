param(
  [string]$PcbFile = "outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb",
  [string]$WorkDir = "outputs\phase4",
  [int]$MaxIterations = 5
)

$ErrorActionPreference = "Stop"

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"
$KiCadCli = Join-Path $KiCadRoot "kicad-cli.exe"

if (!(Test-Path $KiCadPython)) {
  throw "KiCad Python not found at $KiCadPython"
}

if (!(Test-Path $KiCadCli)) {
  throw "kicad-cli not found at $KiCadCli"
}

$env:KICAD_CONFIG_HOME = "C:\Mypcb\.kicad_config"
$env:KICAD_DOCUMENTS_HOME = "C:\Mypcb\.kicad_docs"
$env:HOME = "C:\Mypcb"
$env:USERPROFILE = "C:\Mypcb"
$env:PYTHONPATH = "$KiCadRoot\Lib\site-packages;C:\Mypcb"

& $KiCadPython -m engine.layout_optimizer_service `
  --pcb-file $PcbFile `
  --work-dir $WorkDir `
  --status-output "$WorkDir\layout_optimization_status.json" `
  --kicad-cli $KiCadCli `
  --max-iterations $MaxIterations

Copy-Item "$WorkDir\DRC_REPORT_V1_iteration_1.json" "assets\generated\drc_report_v1.json" -Force -ErrorAction SilentlyContinue
Copy-Item "$WorkDir\layout_optimization_status.json" "assets\generated\layout_optimization_status.json" -Force

# Optimize edilmis final tahta gorunumlerini yeniden uret (PCB/PCBA onizleme guncel kalsin)
& "$PSScriptRoot\render_board_views.ps1" -PcbFile $PcbFile -KiCadCli $KiCadCli
