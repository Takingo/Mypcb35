param(
  [string]$Manufacturer = "PCBWay",
  [string]$OutputDir = "outputs\pcba_manufacturing"
)

$ErrorActionPreference = "Stop"

Write-Host "╔════════════════════════════════════════════════════════════════════╗"
Write-Host "║   PCBA Manufacturing Export Generator                             ║"
Write-Host "║   Target: $Manufacturer"
Write-Host "║   Output: $OutputDir"
Write-Host "╚════════════════════════════════════════════════════════════════════╝"
Write-Host ""

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"

if (!(Test-Path $KiCadPython)) {
  Write-Error "KiCad Python not found at $KiCadPython"
  exit 1
}

$env:PYTHONPATH = "$KiCadRoot\Lib\site-packages;C:\Mypcb;C:\Mypcb\engine"

Write-Host "▶ Starting PCBA manufacturing export service..."
Write-Host ""

& $KiCadPython -m engine.pcba_manufacturing_export_service `
  --manufacturer $Manufacturer `
  --output-dir $OutputDir `
  --asset-output "assets\generated\pcba_manufacturing_package.json"

if ($LASTEXITCODE -eq 0) {
  Write-Host ""
  Write-Host "✓ Export başarılı!" -ForegroundColor Green
  Write-Host ""
  Write-Host "Sonraki adımlar:"
  Write-Host "1. $OutputDir klasörünü açın"
  Write-Host "2. FABRICATION_NOTES.txt adresinde tüm gereksinimler belirtilmiştir"
  Write-Host "3. $($Manufacturer)_UPLOAD_GUIDE.txt adında adım adım talimatlar vardır"
  Write-Host "4. BOM_Extended.csv ve ASSEMBLY_DRAWING.txt'i inceleyin"
  Write-Host "5. Tüm dosyaları $Manufacturer web sitesine yükleyin"
  Write-Host ""
  Write-Host "Web Siteleri:"
  Write-Host "  PCBWay:  https://www.pcbway.com/"
  Write-Host "  JLCPCB:  https://jlc.vip/"
  Write-Host "  Seeed:   https://fusion.seeedstudio.com/"
} else {
  Write-Error "Export işlemi başarısız oldu (Exit code: $LASTEXITCODE)"
  exit 1
}
