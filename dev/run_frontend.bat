@echo off
REM Start the Vite dev server on :5174
cd /d %~dp0\..\frontend
if not exist node_modules (
  echo [setup] Installing npm deps (first run only)…
  call npm install
)
call npm run dev
