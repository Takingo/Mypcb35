param(
  [int]$Quantity = 5,
  [string]$Manufacturer = "PCBWay",
  [string]$SolderMaskColor = "Green"
)

$ErrorActionPreference = "Stop"

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"

if (!(Test-Path $KiCadPython)) {
  throw "KiCad Python not found at $KiCadPython"
}

$env:PYTHONPATH = "$KiCadRoot\Lib\site-packages;C:\Mypcb"

& $KiCadPython -m engine.fabrication_api_service `
  --quantity $Quantity `
  --manufacturer $Manufacturer `
  --solder-mask-color $SolderMaskColor `
  --asset-output "assets\generated\fabrication_package.json"
