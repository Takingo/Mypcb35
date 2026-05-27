param(
  [string]$PcbFile = "outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb",
  [string]$OutputDir = "outputs\assembly",
  [string]$KiCadCli = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
)

# Birlesik tek-dosya tahta gorunumlerini uretir (Flutter PCB/PCBA onizleme icin).
# mode-single: secilen tum katmanlari tek SVG'de ust uste cizer -> gercek tahta gorunumu.

$ErrorActionPreference = "Stop"

if (!(Test-Path $KiCadCli)) {
  throw "kicad-cli bulunamadi: $KiCadCli"
}
if (!(Test-Path $PcbFile)) {
  throw "PCB dosyasi bulunamadi: $PcbFile. Once 'KiCad Uretimi' adimini calistirin."
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "[BoardView] Birlesik tahta gorunumleri uretiliyor..." -ForegroundColor Cyan

# PCB ust katman gorunumu (bakir + maske + silk + pad + kenar)
& $KiCadCli pcb export svg `
  --output (Join-Path $OutputDir "pcb_top.svg") `
  --layers "F.Cu,F.Mask,F.Silkscreen,F.Paste,Edge.Cuts" `
  --mode-single --page-size-mode 2 --fit-page-to-board --exclude-drawing-sheet `
  $PcbFile

# PCB alt katman gorunumu (aynalanmis)
& $KiCadCli pcb export svg `
  --output (Join-Path $OutputDir "pcb_bottom.svg") `
  --layers "B.Cu,B.Mask,B.Silkscreen,Edge.Cuts" `
  --mode-single --page-size-mode 2 --fit-page-to-board --mirror --exclude-drawing-sheet `
  $PcbFile

# PCBA montaj gorunumu (fab + silk + courtyard + kenar) — komponent yerlesimleri
& $KiCadCli pcb export svg `
  --output (Join-Path $OutputDir "pcba_assembly.svg") `
  --layers "F.Fab,F.Silkscreen,F.Courtyard,Edge.Cuts" `
  --mode-single --page-size-mode 2 --fit-page-to-board --exclude-drawing-sheet `
  $PcbFile

if ($LASTEXITCODE -ne 0) {
  Write-Host "[BoardView] HATA: kicad-cli hata kodu $LASTEXITCODE" -ForegroundColor Red
  exit $LASTEXITCODE
}

Write-Host "[BoardView] Tamamlandi: pcb_top.svg, pcb_bottom.svg, pcba_assembly.svg" -ForegroundColor Green
