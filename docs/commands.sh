# Backend one-liner (PowerShell):
Get-Process -Name python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*uvicorn*' } | Stop-Process -Force; Start-Sleep 1; Start-Process -NoNewWindow .venv\Scripts\python.exe "-m uvicorn app:app --port 8765"

# Or even shorter — save this as an alias. The cleanest version using taskkill:
taskkill /F /IM python.exe /FI "WINDOWTITLE eq uvicorn*" 2>$null; Start-Sleep 1; Start-Process -NoNewWindow ".venv\Scripts\python.exe" "-m uvicorn app:app --port 8765"

# Shortest reliable form for day-to-day use:
Stop-Process -Name python -Force -ErrorAction SilentlyContinue; Start-Sleep 1; Start-Process -NoNewWindow .venv\Scripts\python.exe "-m uvicorn app:app --port 8765"

# Frontend one-liner (PowerShell):
Stop-Process -Name node -Force -ErrorAction SilentlyContinue; Start-Sleep 1; Start-Process -NoNewWindow cmd "/c cd frontend && npm run dev"

-------

# to see if server is running, run this command in terminal:
curl -s http://localhost:8000/api/health

command: Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force; Start-Sleep -Seconds 2; Write-Host "All python processes killed"
description: Kill all Python processes

$ until curl -s http://localhost:8000/api/health > /dev/null 2>&1; do sleep 3; done && sleep 30 && curl -s http://localhost:8000/api/health

# perform smoke test
$ cd "C:\Users\HP\Desktop\ai-projects\web-search-rag" && python evals/run_eval.py --smoke --trace on 2>&1

#launch server and front in separate terminals
python -m uvicorn app:app --reload --port 8765
```

then for front
```bash
cd frontend ; npm run dev