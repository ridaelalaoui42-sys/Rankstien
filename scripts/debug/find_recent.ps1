Get-ChildItem -Recurse -File -Path 'c:\Users\REDX420\Desktop\Rankstein' -Exclude '*.pyc','*.bak','*.log','*.png','*.jpg','*.webp' -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -gt [DateTime]'2026-08-01' -and $_.FullName -notmatch '\\(\.venv|node_modules|__pycache__|\.pytest_cache|data\\media|data\\logs|data\\reports|data\\runtime|data\\cache|\.gemini|\.ruff_cache|sessions)\\' } |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 50 FullName, LastWriteTime |
  Format-Table -AutoSize
