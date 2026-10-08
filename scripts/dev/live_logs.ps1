$recentLogs = Get-ChildItem -Path "C:\Users\REDX420\Desktop\Rankstein\data\logs\services\*.log", "C:\Users\REDX420\.gemini\antigravity\brain\e88420cc-43ed-476a-a94c-c3a626a41c6c\.system_generated\tasks\*.log" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3

Write-Host "Starting Unified Live Log Monitor..." -ForegroundColor Cyan
Write-Host "Monitoring the following active log files:" -ForegroundColor Yellow
foreach ($log in $recentLogs) {
    Write-Host " -> $($log.FullName)" -ForegroundColor DarkGray
}
Write-Host "---------------------------------------------------" -ForegroundColor Cyan

Get-Content -Path $recentLogs.FullName -Wait -Tail 15
