# WebLens — Launch & shutdown

## One-time setup

```powershell
# Backend
python -m pip install -r requirements.txt

# Frontend
cd frontend
npm install
cd ..
```

Re-run `npm install` only when `frontend/package.json` changes.

---

## Run dev (two terminals)

**Terminal A — backend** (port `8765`):

```powershell
python -m uvicorn app:app --reload --port 8765
```

**Terminal B — frontend** (port `5174`):

```powershell
cd frontend
npm run dev
```

Open <http://localhost:5174>.

You can also use the convenience launchers:

```powershell
.\dev\run_backend.bat
.\dev\run_frontend.bat
```

---

## List running servers

```powershell
Get-NetTCPConnection -LocalPort 5174,8765,8000 -ErrorAction SilentlyContinue `
  | Select-Object LocalPort, State, OwningProcess `
  | Sort-Object LocalPort
```

To see the actual processes:

```powershell
Get-NetTCPConnection -LocalPort 5174,8765,8000 -ErrorAction SilentlyContinue `
  | ForEach-Object {
      $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
      [pscustomobject]@{ Port=$_.LocalPort; PID=$_.OwningProcess; Name=$p.ProcessName }
    }
```

---

## Kill servers

By **port** (kills any process holding it — Ctrl+C in the dev terminal is preferred when possible):

```powershell
# Backend on :8765
Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue `
  | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }

# Frontend on :5174
Get-NetTCPConnection -LocalPort 5174 -ErrorAction SilentlyContinue `
  | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

By **PID** (after `Get-Process` lookup):

```powershell
Stop-Process -Id <pid> -Force
```

---

## Production build (single-process serving)

```powershell
cd frontend
npm run build
cd ..
python -m uvicorn app:app --port 8765
```

Backend serves `frontend/dist/index.html` at `/` automatically once the build is present.

---

## Eval

```powershell
python evals/run_eval.py --v6-smoke
```

Note: the eval script defaults to `http://localhost:8000`. Either point it
at WebLens explicitly:

```powershell
python evals/run_eval.py --v6-smoke --url http://localhost:8765
```

…or keep an instance running on `:8000` for back-compat.

---

## Useful endpoints

- `GET  /api/health`            — `{ok, env, dev_mode, version}`
- `POST /api/search`            — SSE stream (pipeline events + answer tokens)
- `GET  /api/sessions`          — list sessions
- `DELETE /api/sessions/{id}`   — remove a session
- `GET  /api/eval/results`      — list eval runs
- `GET  /api/eval/questions?set=v6` — load question file

---

## Troubleshooting

- **Port already in use**: another instance is running. Use the kill commands above, or pick a different port (`--port 8766`).
- **`No URLs found. Check TAVILY_API_KEY`**: set `TAVILY_API_KEY` in `.env` at repo root.
- **Sidebar shows old data after delete**: the sidebar refreshes every 30 s — reload to force.
- **Frontend can't reach backend**: confirm `vite.config.ts` proxies `/api` → `:8765` and that the backend is running.
