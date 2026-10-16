param(
    [int]$Port = 3111
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

# Check Native Memory Manager in RankStein
$pythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python.exe"
}

try {
    $check = & $pythonExe -c "from backend.services.memory_service import memory; h = memory.health(); print(f'Native RankStein Memory Manager ({h.get(\`"engine\`")}) healthy with {h.get(\`"total_memories\`", 0)} memories.')"
    Write-Host "[memory] $check"
    exit 0
} catch {
    Write-Error "[memory] Native Memory Manager check failed: $_"
    exit 1
}
