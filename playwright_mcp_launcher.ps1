#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Playwright MCP Launcher for RankStein
  Kills stale Firefox locks then starts playwright-mcp with the configured
  Pinterest session so the MCP server never hangs on profile locks.

.USAGE
  # Default (primary Pinterest session, Firefox):
  .\playwright_mcp_launcher.ps1

  # Specific session:
  .\playwright_mcp_launcher.ps1 -Session turbo_v4

  # Headless mode:
  .\playwright_mcp_launcher.ps1 -Headless

  # CDP mode (connect to existing Chrome):
  .\playwright_mcp_launcher.ps1 -Browser chrome -Port 9222
#>

param(
    [string]$Session    = "pinterest_rida_v7",
    [string]$Browser    = "firefox",
    [switch]$Headless,
    [int]$Port          = 0   # 0 = stdio mode, >0 = SSE server mode
)

# Auto-detect browser based on session if browser is set to default (firefox) or empty
$ChromiumSessions = @("turbo_v4", "turbo_v5", "turbo_v6", "rida_v2_1", "rida_v2_2")
if ($Browser -eq "firefox" -and $ChromiumSessions -contains $Session) {
    $Browser = "chromium"
}

$ProjectRoot  = $PSScriptRoot
$SessionsDir  = Join-Path $ProjectRoot "data\sessions"
$SessionDir   = Join-Path $SessionsDir $Session
$LogDir       = Join-Path $ProjectRoot "data\logs"

# ── Ensure dirs exist ────────────────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $SessionDir | Out-Null
New-Item -ItemType Directory -Force -Path $LogDir     | Out-Null

Write-Host "=== RankStein Playwright MCP Launcher ===" -ForegroundColor Cyan
Write-Host "Session : $SessionDir"
Write-Host "Browser : $Browser"
Write-Host "Headless: True (Mandatory)"

# ── Kill stale processes for this profile ────────────────────────────────────
Write-Host "`n[1/3] Cleaning stale browser locks..." -ForegroundColor Yellow

$ProcName = "firefox.exe"
if ($Browser -eq "chromium" -or $Browser -eq "chrome") {
    $ProcName = "chrome.exe"
}

$LockFiles = @("parent.lock", ".parentlock", "lock",
               "places.sqlite-shm",  "places.sqlite-wal",
               "cookies.sqlite-shm", "cookies.sqlite-wal",
               "webappsstore.sqlite-shm", "webappsstore.sqlite-wal",
               "storage.sqlite-shm",  "storage.sqlite-wal")

$Pids = Get-CimInstance Win32_Process -Filter "Name='$ProcName'" |
    Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($SessionDir.ToLower()) } |
    Select-Object -ExpandProperty ProcessId

foreach ($pid in $Pids) {
    try {
        Stop-Process -Id $pid -Force -ErrorAction Stop
        Write-Host "  Killed $ProcName PID $pid"
    } catch {
        Write-Host "  Could not kill PID $pid : $_"
    }
}

# Wait for processes to release file handles
$deadline = (Get-Date).AddSeconds(6)
while ((Get-Date) -lt $deadline) {
    $still = Get-CimInstance Win32_Process -Filter "Name='$ProcName'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($SessionDir.ToLower()) }
    if (-not $still) { break }
    Start-Sleep -Milliseconds 400
}

foreach ($f in $LockFiles) {
    $path = Join-Path $SessionDir $f
    if (Test-Path $path) {
        try { Remove-Item $path -Force; Write-Host "  Removed $f" }
        catch { Write-Host "  Could not remove $f : $_" }
    }
}

# Remove stale globs
Get-ChildItem -Path $SessionDir -Include "*.pid","*.tmp","lock.*" -Recurse -ErrorAction SilentlyContinue |
    ForEach-Object { try { Remove-Item $_.FullName -Force } catch {} }

Write-Host "  Lock cleanup complete."

# ── Build playwright-mcp arguments ──────────────────────────────────────────
Write-Host "`n[2/3] Building playwright-mcp arguments..." -ForegroundColor Yellow

$args = @(
    "--browser", $Browser,
    "--user-data-dir", $SessionDir,
    "--allow-unrestricted-file-access"
)

# Headless is MANDATORY
$args += "--headless"

if ($Port -gt 0) {
    $args += @("--port", $Port.ToString())
    Write-Host "  Mode: SSE server on port $Port"
} else {
    Write-Host "  Mode: stdio (for MCP client)"
}

# ── Launch ──────────────────────────────────────────────────────────────────
Write-Host "`n[3/3] Starting playwright-mcp..." -ForegroundColor Green
Write-Host "  Command: playwright-mcp.cmd $($args -join ' ')"
Write-Host ""

& playwright-mcp.cmd @args
