param(
    [int]$Port = 3111
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$LogDir = Join-Path $ProjectRoot "data\logs"
$IiiDir = Join-Path $ProjectRoot "tools\iii"
$EnvFile = Join-Path $ProjectRoot ".env"
$LogFile = Join-Path $LogDir "agentmemory.worker.log"
$ErrFile = Join-Path $LogDir "agentmemory.worker.err.log"
$CmdFile = Join-Path $LogDir "agentmemory.worker.cmd"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (Test-Path $EnvFile) {
    foreach ($line in Get-Content -LiteralPath $EnvFile) {
        if ($line -match "^\s*#" -or $line -notmatch "=") {
            continue
        }
        $name, $value = $line.Split("=", 2)
        if ($name) {
            $cleanName = $name.Trim()
            [Environment]::SetEnvironmentVariable($cleanName, $value.Trim(), "Process")
        }
    }
}

$GeminiKey = if ($env:GEMINI_API_KEY) {
    $env:GEMINI_API_KEY
} else {
    [Environment]::GetEnvironmentVariable("GEMINI_API_KEY", "User")
}

$GoogleKey = if ($env:GOOGLE_API_KEY) {
    $env:GOOGLE_API_KEY
} else {
    [Environment]::GetEnvironmentVariable("GOOGLE_API_KEY", "User")
}

if (-not $GeminiKey -and $GoogleKey) {
    $GeminiKey = $GoogleKey
}
if (-not $GoogleKey -and $GeminiKey) {
    $GoogleKey = $GeminiKey
}

if ($GeminiKey) {
    [Environment]::SetEnvironmentVariable("GEMINI_API_KEY", $GeminiKey, "Process")
}
if ($GoogleKey) {
    [Environment]::SetEnvironmentVariable("GOOGLE_API_KEY", $GoogleKey, "Process")
}

$fallbackIii = Join-Path $env:USERPROFILE ".local\bin\iii.exe"
$projectIii = Join-Path $IiiDir "iii.exe"
if (-not (Test-Path $projectIii) -and -not (Test-Path $fallbackIii)) {
    $zipPath = Join-Path $IiiDir "iii-x86_64-pc-windows-msvc.zip"
    New-Item -ItemType Directory -Force -Path $IiiDir | Out-Null
    Invoke-WebRequest `
        -Uri "https://github.com/iii-hq/iii/releases/download/iii%2Fv0.11.2/iii-x86_64-pc-windows-msvc.zip" `
        -OutFile $zipPath
    Expand-Archive -LiteralPath $zipPath -DestinationPath $IiiDir -Force
}

if ((Test-Path $projectIii) -and -not (Test-Path $fallbackIii)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $fallbackIii) | Out-Null
    Copy-Item -LiteralPath $projectIii -Destination $fallbackIii -Force
}

$env:Path = "$IiiDir;$env:Path"
$env:III_REST_PORT = "$Port"
$env:AGENTMEMORY_URL = "http://127.0.0.1:$Port"
$env:AGENTMEMORY_TOOLS = if ($env:AGENTMEMORY_TOOLS) { $env:AGENTMEMORY_TOOLS } else { "core" }
$env:GRAPH_EXTRACTION_ENABLED = if ($env:GRAPH_EXTRACTION_ENABLED) { $env:GRAPH_EXTRACTION_ENABLED } else { "true" }
$env:CONSOLIDATION_ENABLED = if ($env:CONSOLIDATION_ENABLED) { $env:CONSOLIDATION_ENABLED } else { "true" }
$env:AGENTMEMORY_AUTO_COMPRESS = if ($env:AGENTMEMORY_AUTO_COMPRESS) { $env:AGENTMEMORY_AUTO_COMPRESS } else { "true" }
$env:AGENTMEMORY_INJECT_CONTEXT = if ($env:AGENTMEMORY_INJECT_CONTEXT) { $env:AGENTMEMORY_INJECT_CONTEXT } else { "true" }
$env:GEMINI_MODEL = if ($env:GEMINI_MODEL) { $env:GEMINI_MODEL } else { "gemini-3.1-flash-lite-preview" }

try {
    $health = Invoke-RestMethod -Uri "$env:AGENTMEMORY_URL/agentmemory/health" -TimeoutSec 3
    if ($health.status -eq "healthy") {
        Write-Output "AgentMemory already healthy at $env:AGENTMEMORY_URL"
        exit 0
    }
} catch {
}

$npx = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
if (-not $npx) {
    Write-Error "npx.cmd not found. Install Node.js or add it to PATH."
}

Set-Content -LiteralPath $CmdFile -Encoding ASCII -Value @"
@echo off
cd /d "$ProjectRoot"
if not defined GOOGLE_API_KEY set GOOGLE_API_KEY=%GEMINI_API_KEY%
if not defined GEMINI_API_KEY set GEMINI_API_KEY=%GOOGLE_API_KEY%
set EMBEDDING_PROVIDER=local
set AGENTMEMORY_ALLOW_AGENT_SDK=false
set GRAPH_EXTRACTION_ENABLED=$env:GRAPH_EXTRACTION_ENABLED
set CONSOLIDATION_ENABLED=$env:CONSOLIDATION_ENABLED
set AGENTMEMORY_AUTO_COMPRESS=$env:AGENTMEMORY_AUTO_COMPRESS
set AGENTMEMORY_INJECT_CONTEXT=$env:AGENTMEMORY_INJECT_CONTEXT
set GEMINI_MODEL=$env:GEMINI_MODEL
"$npx" -y @agentmemory/agentmemory --port $Port --verbose > "$LogFile" 2> "$ErrFile"
"@

Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", $CmdFile) -WindowStyle Hidden | Out-Null

for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri "$env:AGENTMEMORY_URL/agentmemory/health" -TimeoutSec 3
        if ($health.status -eq "healthy") {
            Write-Output "AgentMemory healthy at $env:AGENTMEMORY_URL"
            exit 0
        }
    } catch {
    }
}

Write-Error "AgentMemory did not become healthy. See $LogFile"
