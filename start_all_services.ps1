#Requires -Version 5.1
<#
  RankStein production suite controller (Thin wrapper for Phase 3 Suite Controller).
  All heavy lifting is now in rankstein.py suite commands.
#>
param(
    [switch]$Daily,
    [switch]$Status,
    [switch]$Stop,
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$SkipFrontend,
    [switch]$SkipOdysseus,
    [ValidatePattern('^\d{2}:\d{2}$')]
    [string]$DailyAt = '06:30'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Canonical Python environment is missing: $Python"
}

if ($Status) {
    & $Python (Join-Path $ProjectRoot 'rankstein.py') suite status
    exit $LASTEXITCODE
}

if ($Stop) {
    & $Python (Join-Path $ProjectRoot 'rankstein.py') suite stop
    exit $LASTEXITCODE
}

if ($Uninstall) {
    & $Python (Join-Path $ProjectRoot 'rankstein.py') suite uninstall
    exit $LASTEXITCODE
}

if ($Install) {
    & $Python (Join-Path $ProjectRoot 'rankstein.py') suite install --daily-at $DailyAt
    exit $LASTEXITCODE
}

if ($Daily) {
    # The daily task triggers the launch workflow directly
    & $Python (Join-Path $ProjectRoot 'rankstein.py') launch --all --keywords 1 --workers 1
} else {
    # Just boot services
    & $Python (Join-Path $ProjectRoot 'rankstein.py') suite start
}
exit $LASTEXITCODE
