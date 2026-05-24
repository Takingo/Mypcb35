param(
  [string]$PcbFile = "outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb",
  [string]$OutputDir = "outputs\assembly"
)

$ErrorActionPreference = "Stop"

$KiCadCli = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"

if (!(Test-Path $KiCadCli)) {
  throw "kicad-cli not found at $KiCadCli"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

& $KiCadCli pcb export pdf `
  --output $OutputDir `
  --layers "F.Fab,F.SilkS,F.Cu,Edge.Cuts" `
  --mode-separate `
  --black-and-white `
  $PcbFile

& $KiCadCli pcb export svg `
  --output $OutputDir `
  --layers "F.Cu,F.Mask,F.SilkS,Edge.Cuts" `
  --mode-multi `
  --fit-page-to-board `
  $PcbFile

& $KiCadCli pcb export glb `
  --output (Join-Path $OutputDir "pcba_preview.glb") `
  --force `
  --include-tracks `
  --include-pads `
  --include-silkscreen `
  --include-soldermask `
  $PcbFile
