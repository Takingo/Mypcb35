$ErrorActionPreference = "Stop"

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"

if (Test-Path $KiCadPython) {
  $Project = "esp32_s3_dwm3000_uwb_anchor_with_relay_outputs"
  $PcbFile = "outputs\kicad\$Project\$Project.kicad_pcb"
  $DrcFile = "outputs\kicad\$Project\manufacturing\drc_report.json"
  if ((Test-Path $PcbFile) -and (Test-Path $DrcFile)) {
    & $KiCadPython -m engine.board_verification_manifest `
      --pcb-file $PcbFile `
      --drc-report-file $DrcFile `
      --netlist-file "outputs\phase1\AI_NETLIST_V1.json" `
      --bom-file "BOM.csv" `
      --output "outputs\engineering\board_verification_manifest.json" `
      --asset-output "assets\generated\board_verification_manifest.json" | Out-Host
  }
  & $KiCadPython -m engine.engineering_readiness_service
} else {
  throw "KiCad Python not found at $KiCadPython"
}
