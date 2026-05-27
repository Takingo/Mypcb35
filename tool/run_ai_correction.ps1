param(
    [switch]$DryRun,
    [string]$ProjectRoot = "C:\Mypcb"
)

$ErrorActionPreference = "Stop"

# KiCad Python environment
$KiCadPython = "C:\Program Files\KiCad\10.0\bin\python.exe"
if (!(Test-Path $KiCadPython)) {
    Write-Host "[ERROR] KiCad Python bulunamadi: $KiCadPython" -ForegroundColor Red
    exit 1
}

$env:PYTHONPATH = $ProjectRoot

Write-Host "[AI-CORRECTION] Onaylanan duzeltmeler uygulaniyorsa..." -ForegroundColor Cyan

$ArgsList = @("-m", "engine.run_ai_correction", "--project-root", $ProjectRoot)
if ($DryRun) {
    $ArgsList += "--dry-run"
    Write-Host "[AI-CORRECTION] Dry-run: hicbir sey degismez." -ForegroundColor Gray
}

& $KiCadPython @ArgsList
$ExitCode = $LASTEXITCODE

Write-Host "[AI-CORRECTION] Bitti." -ForegroundColor Green
exit $ExitCode
