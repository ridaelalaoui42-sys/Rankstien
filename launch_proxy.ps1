# Odysseus Proxy launcher (PowerShell)
# Unsets problematic env vars and starts the proxy in a hidden window
$ErrorActionPreference = 'Stop'
Remove-Item Env:\PYTHONHOME -ErrorAction SilentlyContinue
Remove-Item Env:\UV_INTERNAL__PYTHONHOME -ErrorAction SilentlyContinue
Set-Location C:\Users\REDX420\Desktop\Rankstein
$proc = Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "ody_proxy.py" -PassThru -WindowStyle Hidden
Write-Host "Odysseus Proxy started (PID=$($proc.Id)) on http://127.0.0.1:8000"
Start-Sleep -Seconds 2
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 5
    Write-Host "Health check OK: $($r.Content)"
} catch {
    Write-Warning "Health check failed: $($_.Exception.Message)"
}
