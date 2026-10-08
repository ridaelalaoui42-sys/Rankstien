#Requires -Version 5.1
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$Report = Join-Path $ProjectRoot 'data/runtime/operator_migration.json'
try {
    $Task = Get-ScheduledTask -TaskName 'Odysseus_Server' -ErrorAction SilentlyContinue
    if ($Task) {
        if ($Task.Actions.WorkingDirectory -notmatch 'Desktop\\odysseus$') {
            throw 'Unexpected legacy task ownership; nothing was changed.'
        }
        Disable-ScheduledTask -TaskName 'Odysseus_Server' | Out-Null
    }
    $Result = @{ ok = $true; legacy_task_disabled = $true; updated_at = [DateTime]::UtcNow.ToString('o') }
} catch {
    $Result = @{ ok = $false; error = $_.Exception.Message; updated_at = [DateTime]::UtcNow.ToString('o') }
}
New-Item -ItemType Directory -Path (Split-Path -Parent $Report) -Force | Out-Null
$Result | ConvertTo-Json | Set-Content -LiteralPath $Report -Encoding UTF8
if (-not $Result.ok) { exit 1 }
