$ErrorActionPreference = "Stop"

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"

if (!(Test-Path $KiCadPython)) {
  throw "KiCad Python not found at $KiCadPython"
}

& $KiCadPython -m engine.simulation_service
