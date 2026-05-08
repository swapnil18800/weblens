@echo off
REM Start the FastAPI backend on :8765
cd /d %~dp0\..
python -m uvicorn app:app --reload --port 8765
