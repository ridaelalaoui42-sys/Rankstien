<#
.SYNOPSIS
    RankStein -- Unified MCP System Launch
    Starts all required MCP services before Gemini CLI and optionally boots the
    autonomous supervisor (article workers + Pinterest queue).

.USAGE
    .\scripts\dev\start_all_mcp.ps1              # boot MCP servers + launch Gemini CLI (interactive)
    .\scripts\dev\start_all_mcp.ps1 -StartAll    # boot + launch Gemini CLI with full daily campaign (YOLO)
    .\scripts\dev\start_all_mcp.ps1 -NoGemini    # boot servers only (no Gemini CLI)
    .\scripts\dev\start_all_mcp.ps1 -WithSupervisor  # also start Pinterest + article workers
    .\scripts\dev\start_all_mcp.ps1 -StatusOnly  # health check only
#>

param(
    [int]$AgentMemoryPort = 3111,
    [switch]$NoGemini,
    [switch]$WithSupervisor,
    [switch]$StatusOnly,
    [switch]$StartAll   # Run full daily campaign prompt in YOLO mode automatically
)

$ErrorActionPreference = "Continue"

$ProjectRoot  = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
$LogDir       = Join-Path $ProjectRoot "data\logs"
$EnvFile      = Join-Path $ProjectRoot ".env"
$Python       = "python"
$NpxCmd       = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
$GeminiCmd    = (Get-Command gemini.cmd -ErrorAction SilentlyContinue).Source

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ── 0. Load .env ──────────────────────────────────────────────────────────────
Write-Host "`n[RankStein] Loading environment from .env..." -ForegroundColor Cyan
if (Test-Path $EnvFile) {
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
        $parts = $line.Split("=", 2)
        if ($parts[0].Trim()) {
            [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
        }
    }
    Write-Host "  .env loaded OK" -ForegroundColor Green
} else {
    Write-Host "  WARNING: .env not found at $EnvFile" -ForegroundColor Yellow
}

# Cross-populate API keys
if (-not $env:GEMINI_API_KEY -and $env:GOOGLE_API_KEY) { $env:GEMINI_API_KEY = $env:GOOGLE_API_KEY }
if (-not $env:GOOGLE_API_KEY -and $env:GEMINI_API_KEY) { $env:GOOGLE_API_KEY = $env:GEMINI_API_KEY }

# ── Helper: health check ──────────────────────────────────────────────────────
function Wait-Http {
    param([string]$Url, [int]$Retries = 20, [int]$DelaySeconds = 1, [string]$Name = "service")
    for ($i = 0; $i -lt $Retries; $i++) {
        try {
            $r = Invoke-RestMethod -Uri $Url -TimeoutSec 3 -ErrorAction Stop
            if ($r.status -eq "healthy" -or $r.status -eq "ok" -or $r.ok -eq $true) {
                return $true
            }
        } catch { }
        Start-Sleep -Seconds $DelaySeconds
    }
    return $false
}

function Check-ProcessRunning {
    param([string]$Name)
    return ($null -ne (Get-Process -Name $Name -ErrorAction SilentlyContinue))
}

# ── 1. AgentMemory HTTP server ────────────────────────────────────────────────
Write-Host "`n[1/5] AgentMemory HTTP server (port $AgentMemoryPort)..." -ForegroundColor Cyan
$HealthUrl = "http://127.0.0.1:$AgentMemoryPort/agentmemory/health"
$AlreadyUp = $false
try {
    $h = Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3 -ErrorAction Stop
    if ($h.status -eq "healthy") { $AlreadyUp = $true }
} catch { }

if ($AlreadyUp) {
    Write-Host "  AgentMemory already running -- skipping launch" -ForegroundColor Green
} else {
    Write-Host "  Starting AgentMemory..." -ForegroundColor Yellow
    & "$PSScriptRoot\start_agentmemory.ps1" -Port $AgentMemoryPort
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARNING: AgentMemory may not be healthy (exit $LASTEXITCODE)" -ForegroundColor Yellow
    } else {
        Write-Host "  AgentMemory OK" -ForegroundColor Green
    }
}

# ── 2. Validate RankStein MCP server (stdio -- Gemini manages it) ──────────────
Write-Host "`n[2/5] RankStein MCP server (stdio, Gemini-managed)..." -ForegroundColor Cyan
$RanksteinServer = Join-Path $ProjectRoot "rankstein_mcp_server.py"
if (Test-Path $RanksteinServer) {
    $SyntaxCheck = & $Python -m py_compile $RanksteinServer 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  rankstein_mcp_server.py syntax OK" -ForegroundColor Green
    } else {
        Write-Host "  ERROR: rankstein_mcp_server.py syntax error:`n$SyntaxCheck" -ForegroundColor Red
    }
} else {
    Write-Host "  ERROR: rankstein_mcp_server.py not found at $RanksteinServer" -ForegroundColor Red
}

# ── 3. Validate NanaBanana MCP server (stdio -- Gemini-managed) ───────────────
Write-Host "`n[3/5] NanaBanana MCP server (stdio, Gemini-managed)..." -ForegroundColor Cyan
$NanaBananaJs = Join-Path $ProjectRoot "nanobanana-extension\mcp-server\dist\index.js"
if (Test-Path $NanaBananaJs) {
    Write-Host "  nanobanana dist/index.js found OK" -ForegroundColor Green
} else {
    Write-Host "  WARNING: NanaBanana dist not found -- run 'npm run build' in nanobanana-extension\mcp-server" -ForegroundColor Yellow
}

# ── 4. Validate Playwright MCP (stdio -- Gemini-managed) ──────────────────────
Write-Host "`n[4/5] Playwright MCP (stdio, Gemini-managed)..." -ForegroundColor Cyan
$PlaywrightMcp = (Get-Command playwright-mcp.cmd -ErrorAction SilentlyContinue).Source
if ($PlaywrightMcp) {
    Write-Host "  playwright-mcp.cmd found: $PlaywrightMcp" -ForegroundColor Green
} else {
    Write-Host "  WARNING: playwright-mcp.cmd not in PATH. Run: npm install -g @playwright/mcp" -ForegroundColor Yellow
}

# ── 5. Supabase MCP (HTTP remote -- no local process needed) ──────────────────
Write-Host "`n[5/5] Supabase MCP (remote HTTP -- no local process needed)..." -ForegroundColor Green
Write-Host "  Configured as remote HTTP endpoint in .gemini/settings.json" -ForegroundColor Green

# ── Status summary ────────────────────────────────────────────────────────────
Write-Host "`n────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host " MCP Server Status Summary" -ForegroundColor White
Write-Host "────────────────────────────────────────────────────────" -ForegroundColor DarkGray
$amStatus = try { (Invoke-RestMethod -Uri $HealthUrl -TimeoutSec 3).status } catch { "offline" }
Write-Host "  agentmemory      : $amStatus" -ForegroundColor $(if ($amStatus -eq "healthy") { "Green" } else { "Red" })
Write-Host "  rankstein        : stdio (Gemini auto-starts)" -ForegroundColor Green
Write-Host "  nanobanana       : stdio (Gemini auto-starts)" -ForegroundColor Green
Write-Host "  playwright_ff    : stdio (Gemini auto-starts)" -ForegroundColor Green
Write-Host "  playwright_cr    : stdio (Gemini auto-starts)" -ForegroundColor Green
Write-Host "  supabase         : remote HTTP (always available)" -ForegroundColor Green

if ($StatusOnly) {
    Write-Host "`nStatus check complete. Exiting." -ForegroundColor Cyan
    exit 0
}

# ── Optional: Start Autonomous Supervisor ─────────────────────────────────────
if ($WithSupervisor) {
    Write-Host "`n[AUTO] Starting autonomous supervisor + article workers..." -ForegroundColor Cyan
    $SupervisorLog = Join-Path $LogDir "supervisor.log"
    $SupervisorErr = Join-Path $LogDir "supervisor_err.log"
    Start-Process -FilePath $Python `
        -ArgumentList @((Join-Path $ProjectRoot "run_autonomous.py"), "run") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $SupervisorLog `
        -RedirectStandardError $SupervisorErr `
        -WindowStyle Hidden
    Write-Host "  Supervisor started. Logs: $SupervisorLog" -ForegroundColor Green
}

# ── Daily campaign prompt (used by -StartAll) ────────────────────────────────
$DailyCampaignPrompt = @'
START ALL -- Execute the full RankStein daily campaign for ALL domains automatically.
Follow GEMINI.md Required Start Of Run and Required Pipeline Shape exactly:
1) list_domains()
2) multidomain_startup_brief()
3) process_pinterest_backlog()
4) start_automation_supervisor()
5) Run shell command: python run_autonomous.py enqueue-folder  (queues ALL remastered pins from data/media/remaster_final/ for all accounts -- supervisor handles uploads)
6) memory_stats()
7) search_project_memory for recent failures, selector changes, and account issues for EACH domain.
8) For EACH ready domain, pick ALL pending keywords and run the full 17-step article pipeline:
   scrape_news_sources -> extract_article_content -> generate article JSON (never empty arrays) ->
   validate_article_quality (revise up to 3x) -> create_hero_image_pollinations ->
   upload_image_to_supabase -> create_article_pin -> automation_upload_pin_direct (get pin_id) ->
   build_supabase_content (inject pin_id) -> publish_article_to_supabase (with domain_handle) ->
   mark keyword Live -> remember_pipeline_event.
9) Report final status for every keyword across all domains AND remaster queue depth.
Do NOT ask questions, do NOT stop, do NOT skip any domain or the remaster step. Execute everything autonomously.
'@

# ── Launch Gemini CLI ─────────────────────────────────────────────────────────
if (-not $NoGemini) {
    if (-not $GeminiCmd) {
        Write-Host "`nERROR: gemini.cmd not found in PATH. Install with: npm install -g @google/gemini-cli" -ForegroundColor Red
        exit 1
    }

    if ($StartAll) {
        Write-Host "`n[START ALL] Launching Gemini CLI with full daily campaign (YOLO mode)..." -ForegroundColor Magenta
        Write-Host "  All MCP servers ready. Campaign starting across all domains.`n" -ForegroundColor Green
        & $GeminiCmd --yolo --prompt $DailyCampaignPrompt
    } else {
        Write-Host "`n[LAUNCH] Starting Gemini CLI (interactive)..." -ForegroundColor Cyan
        Write-Host "  All MCP servers ready. Entering interactive session.`n" -ForegroundColor Green
        & $GeminiCmd
    }
} else {
    Write-Host "`nAll MCP servers ready. Skipping Gemini CLI (-NoGemini)." -ForegroundColor Cyan
}

