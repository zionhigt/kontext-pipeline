@echo off
REM Demarre ComfyUI en daemon local sur 127.0.0.1:8188
REM Pas de --lowvram sur A4500 20 Go en FP8 (cf. CDC §5.5)
REM Si `extra_model_paths.yaml` existe a la racine du projet, il est
REM injecte automatiquement (modeles sur un autre disque, cf. README).

cd /d "%~dp0.."
call conda activate kontext || exit /b 1

set EXTRA_PATHS=
if exist "%cd%\extra_model_paths.yaml" (
  set EXTRA_PATHS=--extra-model-paths-config "%cd%\extra_model_paths.yaml"
  echo Utilisation de extra_model_paths.yaml
)

pushd ComfyUI
python main.py --listen 127.0.0.1 --port 8188 %EXTRA_PATHS%
popd
