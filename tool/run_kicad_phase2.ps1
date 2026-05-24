param(
  [string]$Netlist = "outputs\phase1\AI_NETLIST_V1.example.json",
  [string]$OutputRoot = "outputs\kicad",
  [switch]$Export,
  [switch]$ContinueOnDrcError
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

$ArgsList = @(
  "-m",
  "engine.kicad_automation_service",
  "--netlist",
  $Netlist,
  "--output-root",
  $OutputRoot,
  "--kicad-cli",
  $KiCadCli
)

if ($Export) {
  $ArgsList += "--export"
}

if ($ContinueOnDrcError) {
  $ArgsList += "--continue-on-drc-error"
}

& $KiCadPython @ArgsList
