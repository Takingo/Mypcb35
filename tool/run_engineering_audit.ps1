$ErrorActionPreference = "Stop"

$KiCadRoot = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"

if (Test-Path $KiCadPython) {
  & $KiCadPython -m engine.engineering_readiness_service
} else {
  throw "KiCad Python not found at $KiCadPython"
}
