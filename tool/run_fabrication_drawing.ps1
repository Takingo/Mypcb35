param(
  [string]$PcbFile = "outputs\kicad\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs\esp32_s3_dwm3000_uwb_anchor_with_relay_outputs.kicad_pcb",
  [string]$OutputDir = "outputs\fabrication_drawing",
  [string]$KiCadCli = "C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"
)

$ErrorActionPreference = "Stop"

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"

if (!(Test-Path $KiCadPython)) {
  throw "KiCad Python bulunamadi: $KiCadPython"
}

$env:PYTHONPATH = "$KiCadRoot\Lib\site-packages;C:\Mypcb"

Write-Host "[FabDraw] Fabrication drawing uretimi basladi..." -ForegroundColor Cyan

& $KiCadPython -m engine.fabrication_drawing_service `
  --pcb-file $PcbFile `
  --output-dir $OutputDir `
  --kicad-cli $KiCadCli

if ($LASTEXITCODE -ne 0) {
  Write-Host "[FabDraw] HATA: Servis hata kodu $LASTEXITCODE ile sonlandi." -ForegroundColor Red
  exit $LASTEXITCODE
}

Write-Host "[FabDraw] Tamamlandi. Ciktilar: $OutputDir" -ForegroundColor Green
Write-Host ""
Write-Host "Uretilen dosyalar:"
Get-ChildItem $OutputDir -ErrorAction SilentlyContinue | ForEach-Object {
  Write-Host "  $($_.Name)  ($([math]::Round($_.Length / 1KB, 1)) KB)"
}
