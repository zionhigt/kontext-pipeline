@echo off
REM Demarre le backend FastAPI (port 8000)
call conda activate kontext || exit /b 1
set PYTHONPATH=%cd%
uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
