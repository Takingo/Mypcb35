param(
  [Parameter(Mandatory = $true)][string]$Engineer,
  [switch]$All,
  [string[]]$Items = @(),
  [string]$Notes = ""
)

# Manuel mühendislik sign-off kaydi (datasheet/RF/AC/SPICE maddeleri).
# Bu, otomatik dogrulanamayan maddeleri bir GERCEK mühendisin imzaladigini
# denetlenebilir sekilde kaydeder. Sonra run_simulation_checks + audit calistir.

$ErrorActionPreference = "Stop"
$KiCadPython = "C:\Program Files\KiCad\10.0\bin\python.exe"
if (!(Test-Path $KiCadPython)) { throw "KiCad Python not found: $KiCadPython" }
$env:PYTHONPATH = "C:\Mypcb"

$ArgsList = @("-m", "engine.manual_signoff", "--engineer", $Engineer, "--project-root", "C:\Mypcb")
if ($All) { $ArgsList += "--all" }
if ($Items.Count -gt 0) { $ArgsList += "--items"; $ArgsList += $Items }
if ($Notes) { $ArgsList += @("--notes", $Notes) }

Write-Host "[SIGNOFF] Manuel mühendislik imzasi kaydediliyor ($Engineer)..." -ForegroundColor Cyan
& $KiCadPython @ArgsList

Write-Host "[SIGNOFF] Sonra: .\tool\run_simulation_checks.ps1 ve .\tool\run_engineering_audit.ps1" -ForegroundColor Green
