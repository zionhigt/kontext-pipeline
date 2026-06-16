@echo off
REM Arret propre du daemon ComfyUI : libere la VRAM pour Hunyuan (cf. CDC §8).
REM Cible le process python qui ecoute sur 8188.

for /f "tokens=5" %%P in ('netstat -ano ^| findstr :8188 ^| findstr LISTENING') do (
  echo Tue PID %%P
  taskkill /PID %%P /F
)

echo.
echo Verification VRAM:
nvidia-smi --query-gpu=memory.used,memory.free --format=csv
