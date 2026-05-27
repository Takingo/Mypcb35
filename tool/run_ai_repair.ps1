param(
  [switch]$Apply,
  [double]$Confidence = 0.6
)

# OmniCircuit kapali-dongu AI tamir + Girdi Paneli kanit dogrulama.
# - Once girdi (BOM<->netlist) tutarliligini denetler.
# - Sonra aktif AI saglayicidan (ai_settings.json) tamir onerisi alir,
#   deterministik gate'ten gecirir, candidate uretir.
# - -Apply verilirse candidate'i KiCad ile re-verify edip yalnizca regresyon
#   yoksa canli netliste yazar (yoksa rollback).
#
# Durustluk: hicbir AI degisikligi KiCad DRC ile kanitlanmadan canliya yazilmaz.

$ErrorActionPreference = "Stop"

$KiCadRoot   = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"
if (!(Test-Path $KiCadPython)) { throw "KiCad Python not found: $KiCadPython" }

$env:PYTHONPATH = "C:\Mypcb"

Write-Host "[AI-REPAIR] Girdi Paneli kanit dogrulamasi..." -ForegroundColor Cyan
& $KiCadPython -m engine.input_evidence_validator --project-root "C:\Mypcb"

Write-Host "[AI-REPAIR] Aktif AI saglayicidan tamir onerisi (ai_settings.json)..." -ForegroundColor Cyan
$ArgsList = @("-m", "engine.ai_repair_service", "--project-root", "C:\Mypcb", "--confidence", "$Confidence")
if ($Apply) {
  $ArgsList += "--apply"
  Write-Host "[AI-REPAIR] -Apply: candidate KiCad re-verify ile dogrulanacak (regresyon yoksa canliya yazilir)." -ForegroundColor Yellow
} else {
  Write-Host "[AI-REPAIR] Dry-run: oneri + dogrulama (canli netlist degismez). Uygulamak icin -Apply." -ForegroundColor Gray
}

& $KiCadPython @ArgsList
$ExitCode = $LASTEXITCODE

Write-Host "[AI-REPAIR] Bitti. Cikti: outputs\engineering\ai_repair_log.json + input_evidence_report.json" -ForegroundColor Green
exit $ExitCode
