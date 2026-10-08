param(
    [switch]$NoGemini,
    [switch]$StatusOnly,
    [switch]$WithSupervisor,
    [switch]$StartAll
)

$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

Write-Host "RankStein MCP Bootstrapping..." -ForegroundColor Cyan

# Avoid Python stdlib mismatches when PowerShell inherits uv/Hermes Python-home vars
# but `python` resolves to a different interpreter on PATH.
Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:UV_INTERNAL__PYTHONHOME -ErrorAction SilentlyContinue

# 1. Load .env for credentials
$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Write-Host "[boot] Loading environment from $EnvFile"
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
        $name, $value = $line.Split("=", 2)
        if ($name) {
            $cleanName = $name.Trim()
            $cleanValue = $value.Trim()
            [Environment]::SetEnvironmentVariable($cleanName, $cleanValue, "Process")
        }
    }
}

# 2. Start AgentMemory (Foundational)
$agentMemoryScript = Join-Path $PSScriptRoot "start_agentmemory.ps1"
if (Test-Path $agentMemoryScript) {
    Write-Host "[boot] Starting AgentMemory server..."
    & $agentMemoryScript
} else {
    Write-Error "[boot] CRITICAL: start_agentmemory.ps1 not found in $PSScriptRoot"
    exit 1
}

# 3. Validate RankStein MCP Server syntax
$mcpServer = Join-Path $ProjectRoot "rankstein_mcp_server.py"
if (Test-Path $mcpServer) {
    Write-Host "[boot] Validating rankstein_mcp_server.py syntax..."
    python -m py_compile $mcpServer
    if ($LASTEXITCODE -ne 0) {
        Write-Error "[boot] rankstein_mcp_server.py has syntax errors. Fix them before proceeding."
        exit 1
    }
}

# 4. Verify Supabase Connectivity
if ($env:NEXT_PUBLIC_SUPABASE_URL) {
    Write-Host "[boot] Supabase URL detected: $($env:NEXT_PUBLIC_SUPABASE_URL)"
} else {
    Write-Warning "[boot] Supabase URL not found in environment."
}

# 5. Optional Supervisor Launch
if ($WithSupervisor -or $StartAll) {
    Write-Host "[boot] Starting Autonomous Pinterest Supervisor..." -ForegroundColor Yellow
    $autonomousScript = Join-Path $ProjectRoot "run_autonomous.py"
    if (Test-Path $autonomousScript) {
        $pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
        if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }
        Start-Process -FilePath $pythonExe -ArgumentList @($autonomousScript, "run") -WorkingDirectory $ProjectRoot -WindowStyle Hidden
        Write-Host "[boot] Autonomous supervisor spawned in background." -ForegroundColor Green
    } else {
        Write-Warning "[boot] run_autonomous.py not found in $ProjectRoot"
    }
}

Write-Host "[boot] All MCP infrastructure checks passed." -ForegroundColor Green

if ($StatusOnly) {
    exit 0
}

# 6. Interactive Gemini CLI Launch
if (-not $NoGemini) {
    Write-Host "[boot] Launching Gemini CLI interactive session..." -ForegroundColor Cyan
    $geminiCmd = $null
    if ($env:GEMINI_CLI_PATH -and (Test-Path $env:GEMINI_CLI_PATH)) {
        $geminiCmd = $env:GEMINI_CLI_PATH
    } elseif ($env:APPDATA -and (Test-Path (Join-Path $env:APPDATA "npm\gemini.cmd"))) {
        $geminiCmd = Join-Path $env:APPDATA "npm\gemini.cmd"
    } else {
        $geminiCmd = (Get-Command gemini.cmd -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
        if (-not $geminiCmd) {
            $geminiCmd = (Get-Command gemini -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1)
        }
    }

    if ($geminiCmd) {
        # Strip API keys to ensure subscription/OAuth mode is used per contract
        Remove-Item Env:GOOGLE_API_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
        & $geminiCmd
    } else {
        Write-Warning "[boot] Gemini CLI executable not found. Install globally via 'npm i -g @google/gemini-cli' or set GEMINI_CLI_PATH."
    }
}
