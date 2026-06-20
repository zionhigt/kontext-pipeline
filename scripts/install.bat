@echo off
REM ============================================================
REM  Install Kontext Pipeline — Windows, conda, CUDA 12.4
REM  cf. docs/CDC_kontext_pipeline.md §5
REM ============================================================

setlocal

REM Se placer a la racine du projet (le dossier parent de scripts\)
cd /d "%~dp0.."

echo [1/6] Creation env conda 'kontext' (Python 3.10)...
call conda create -n kontext python=3.10 -y || goto :err
call conda activate kontext || goto :err

echo [2/6] pip up-to-date...
python -m pip install --upgrade pip || goto :err

echo [3/6] PyTorch 2.6.0 + CUDA 12.4 (NE PAS retirer --index-url, cf. CDC §3.2)...
pip install torch==2.6.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 || (
  echo torch 2.6.0+cu124 indisponible, repli sur 2.7.0+cu124
  pip install torch==2.7.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 || goto :err
)

echo [4/6] Clone ComfyUI...
if not exist ComfyUI (
  git clone https://github.com/comfyanonymous/ComfyUI || goto :err
)
pushd ComfyUI
pip install -r requirements.txt || goto :err
popd

echo [5/6] Dependances backend FastAPI...
pip install -r backend\requirements.txt || goto :err

echo [6/6] Verification CUDA / GPU...
python -c "import torch; print('torch', torch.__version__); print('cuda', torch.cuda.is_available()); print('device', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none'); print('bf16', torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False)" || goto :err

echo.
echo === Install OK ===
echo Prochaines etapes :
echo   1) Telecharger les modeles FLUX.1 Kontext (cf. CDC §5.4) dans ComfyUI\models\
echo   2) scripts\start_comfy.bat
echo   3) scripts\start_backend.bat
exit /b 0

:err
echo.
echo === ECHEC INSTALL ===
exit /b 1
