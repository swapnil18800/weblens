# to see if server is running, run this command in terminal:
curl -s http://localhost:8000/api/health

command: Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 2; Write-Host "All python processes killed"
description: Kill all Python processes

$ until curl -s http://localhost:8000/api/health > /dev/null 2>&1; do sleep 3; done && sleep 30 && curl -s http://localhost:8000/api/health