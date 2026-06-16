@echo off
REM Demarre ComfyUI en daemon local sur 127.0.0.1:8188
REM Pas de --lowvram sur A4500 20 Go en FP8 (cf. CDC §5.5)
cd /d "%~dp0.."
call conda activate kontext || exit /b 1
pushd ComfyUI
python main.py --listen 127.0.0.1 --port 8188
popd
