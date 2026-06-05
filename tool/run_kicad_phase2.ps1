param(
  [string]$OutputRoot = "outputs\kicad",
  [switch]$Export,
  [switch]$ContinueOnDrcError
)

$ErrorActionPreference = "Stop"

$KiCadRoot   = "C:\Program Files\KiCad\10.0\bin"
$KiCadPython = Join-Path $KiCadRoot "python.exe"
$KiCadCli    = Join-Path $KiCadRoot "kicad-cli.exe"

if (!(Test-Path $KiCadPython)) { throw "KiCad Python not found: $KiCadPython" }
if (!(Test-Path $KiCadCli))    { throw "kicad-cli not found: $KiCadCli" }

# KiCad environment
$env:KICAD_CONFIG_HOME    = "C:\Mypcb\.kicad_config"
$env:KICAD_DOCUMENTS_HOME = "C:\Mypcb\.kicad_docs"
$env:HOME                 = "C:\Mypcb"
$env:USERPROFILE          = "C:\Mypcb"
$env:PYTHONPATH           = "$KiCadRoot\Lib\site-packages;C:\Mypcb;C:\Mypcb\engine"

# Netlist selection: prefer the user-generated design, fall back to the sample.
# Flutter writes AI_NETLIST_V1.json after Generate.
$RealNetlist    = "outputs\phase1\AI_NETLIST_V1.json"
$ExampleNetlist = "outputs\phase1\AI_NETLIST_V1.example.json"

if (Test-Path $RealNetlist) {
    $Netlist = $RealNetlist
    Write-Host "[PHASE2] Using real user netlist: $Netlist" -ForegroundColor Green
} elseif (Test-Path $ExampleNetlist) {
    $Netlist = $ExampleNetlist
    Write-Host "[PHASE2] WARNING: User netlist not found. Using sample: $Netlist" -ForegroundColor Yellow
} else {
    throw "Netlist file not found. Generate the design package first."
}

Write-Host "[PHASE2] Normalizing source evidence against BOM..." -ForegroundColor Cyan
& $KiCadPython -m engine.netlist_source_normalizer --netlist $Netlist --bom "BOM.csv"
if ($LASTEXITCODE -ne 0) {
    throw "Netlist source normalization failed."
}

# Run Python KiCad automation service.
$ArgsList = @(
    "-m", "engine.kicad_automation_service",
    "--netlist",      $Netlist,
    "--output-root",  $OutputRoot,
    "--kicad-cli",    $KiCadCli,
    "--project-root", "C:\Mypcb"
)

if ($Export)           { $ArgsList += "--export" }
if ($ContinueOnDrcError) { $ArgsList += "--continue-on-drc-error" }

Write-Host "[PHASE2] Starting KiCad automation..." -ForegroundColor Cyan
& $KiCadPython @ArgsList
$ExitCode = $LASTEXITCODE
if ($ExitCode -ne 0) {
    Write-Host "[PHASE2] KiCad automation failed. Stale DRC/manifest will not be reused." -ForegroundColor Red
    exit $ExitCode
}

# Copy the real DRC report into Flutter assets when available.
# kicad_automation_service also writes this, but this keeps export=false useful.
$AssetsDir = "C:\Mypcb\assets\generated"
if (!(Test-Path $AssetsDir)) { New-Item -ItemType Directory -Force $AssetsDir | Out-Null }

# Real DRC report under the manufacturing folder.
$DrcSource = Get-ChildItem "$OutputRoot\*\manufacturing\drc_report.json" -Recurse -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending |
             Select-Object -First 1

if ($DrcSource) {
    Write-Host "[PHASE2] Found real DRC report: $($DrcSource.FullName)" -ForegroundColor Cyan

    # Convert KiCad JSON into the Flutter dashboard shape.
    try {
        $DrcRaw = Get-Content $DrcSource.FullName -Raw | ConvertFrom-Json
        [array]$Violations = if ($null -ne $DrcRaw.violations) { @($DrcRaw.violations) } elseif ($null -ne $DrcRaw.items) { @($DrcRaw.items) } else { @() }
        # DURUSTLUK: unconnected_items KiCad'de ayri tutulur ama bunlar ERROR'dur.
        [array]$Unconnected = if ($null -ne $DrcRaw.unconnected_items) { @($DrcRaw.unconnected_items) } else { @() }
        $TotalV = $Violations.Count + $Unconnected.Count

        $FlutterDrc = @{
            schema          = "drc_report_v1"
            generated_at    = (Get-Date -Format "o")
            total_violations = $TotalV
            status          = if ($TotalV -eq 0) { "pass" } else { "fail" }
            source          = "kicad_cli_real_drc"
            violations_summary = @{
                clearance    = ($Violations | Where-Object { $_.type -match "clearance" }).Count
                unconnected  = $Unconnected.Count + ($Violations | Where-Object { $_.type -match "unconnected" }).Count
                solder_mask  = ($Violations | Where-Object { $_.type -match "solder_mask" }).Count
                silk         = ($Violations | Where-Object { $_.type -match "silk" }).Count
                other        = [Math]::Max(0, $TotalV - ($Violations | Where-Object { $_.type -match "clearance|unconnected|solder_mask|silk" }).Count)
            }
            full_report_path = $DrcSource.FullName
        }

        $FlutterDrc | ConvertTo-Json -Depth 5 | Out-File "$AssetsDir\drc_report_v1.json" -Encoding utf8
        $DrcColor = if ($TotalV -eq 0) { "Green" } else { "Yellow" }
        Write-Host "[PHASE2] DRC report written to assets: $TotalV violation(s)" -ForegroundColor $DrcColor

        $ProjectDir = Split-Path -Parent (Split-Path -Parent $DrcSource.FullName)
        $PcbSource = Get-ChildItem $ProjectDir -Filter "*.kicad_pcb" -ErrorAction SilentlyContinue |
                     Sort-Object LastWriteTime -Descending |
                     Select-Object -First 1
        if (!$PcbSource) {
            throw "PCB file not found beside DRC report: $ProjectDir"
        }

        & $KiCadPython -m engine.board_verification_manifest `
            --pcb-file $PcbSource.FullName `
            --drc-report-file $DrcSource.FullName `
            --netlist-file $Netlist `
            --bom-file "BOM.csv" `
            --output "outputs\engineering\board_verification_manifest.json" `
            --asset-output "$AssetsDir\board_verification_manifest.json"
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[PHASE2] Board verification manifest: production_candidate" -ForegroundColor Green
        } else {
            Write-Host "[PHASE2] Board verification manifest: blocked" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[PHASE2] WARNING: DRC conversion failed: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "[PHASE2] DRC report not found yet; use -Export to generate it." -ForegroundColor Gray
}

Write-Host "[PHASE2] Finished. Exit code: $ExitCode"
exit $ExitCode
