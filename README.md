# Kontext Pipeline

Service local d'édition d'image guidée par texte basé sur **FLUX.1 Kontext [dev]**, exposé via une interface web. Étape amont du pipeline de génération 3D Hunyuan.

Cahier des charges détaillé : [`docs/CDC_kontext_pipeline.md`](docs/CDC_kontext_pipeline.md).

## Architecture

```
Front (HTML/JS)  ──▶  Backend FastAPI  ──▶  ComfyUI daemon (FLUX.1 Kontext FP8)
                       :8000                 :8188
```

Le backend ne charge aucun modèle : il pilote ComfyUI en HTTP (`POST /prompt`, polling `/history`, fetch `/view`).

## Cible

- Windows natif (pas WSL), GPU **RTX A4500 / 20 Go VRAM**
- Python **3.10** (conda env `kontext`)
- CUDA toolkit **12.4**, PyTorch **2.6.0+cu124**
- Variante modèle : **FP8 scaled (~12 Go)**

## Arborescence

```
kontext-pipeline/
├── backend/
│   ├── app.py                          # FastAPI : /edit /status /result
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   └── assets/{app.js,style.css}
├── workflows/
│   └── kontext_api_template.json       # À remplacer par export Save (API Format)
├── scripts/
│   ├── install.bat
│   ├── start_comfy.bat
│   ├── start_backend.bat
│   └── stop_comfy.bat
├── docs/
│   └── CDC_kontext_pipeline.md
└── README.md
```

## Installation

```bat
scripts\install.bat
```

Étapes effectuées :
1. `conda create -n kontext python=3.10`
2. PyTorch 2.6.0+cu124 (avec `--index-url` : sans, on récupère le wheel **CPU**, cf. CDC §3.2)
3. Clone `ComfyUI` + `pip install -r requirements.txt`
4. Dépendances backend (`fastapi`, `uvicorn`, `pillow`, …)
5. Vérification CUDA / device

Aucun `deepspeed`, aucun `bpy` (cf. CDC §3.1).

### Modèles (à télécharger manuellement)

Dépôt gated HuggingFace `black-forest-labs/FLUX.1-Kontext-dev` — accepter la licence non-commerciale.

| Fichier | Destination |
|---|---|
| `flux1-kontext-dev` FP8 scaled (`.safetensors`) | `ComfyUI/models/diffusion_models/` |
| `clip_l.safetensors` | `ComfyUI/models/text_encoders/` |
| `t5xxl_fp8_e4m3fn.safetensors` | `ComfyUI/models/text_encoders/` |
| `ae.safetensors` (VAE) | `ComfyUI/models/vae/` |

### Template workflow

`workflows/kontext_api_template.json` est un **modèle indicatif**. Pour garantir la cohérence des `class_type` / liens entre nodes :

1. Charger un workflow Kontext minimal dans ComfyUI : `Load Image → CLIP/T5 encode → Kontext → VAE decode → Save Image`.
2. Activer Dev Mode (Settings).
3. **Save (API Format)** → remplacer le fichier.
4. Vérifier que les IDs de nodes correspondent aux constantes `NODE_*` dans `backend/app.py` (`LOAD_IMAGE`, `PROMPT_TEXT`, `KSAMPLER`, `FLUX_GUIDANCE`). Si l'export utilise des IDs numériques, ajuster les constantes.

## Lancement

Dans deux terminaux séparés (env `kontext` activé) :

```bat
scripts\start_comfy.bat       :: daemon ComfyUI sur :8188
scripts\start_backend.bat     :: backend FastAPI sur :8000
```

Puis ouvrir <http://127.0.0.1:8000>.

## Séquençage avec Hunyuan

Kontext et Hunyuan ne tournent **jamais simultanément** (VRAM partagée 20 Go).

1. `start_comfy.bat` + `start_backend.bat` → éditer le batch d'images
2. `stop_comfy.bat` → libère la VRAM (vérifié `nvidia-smi`)
3. Lancer le pipeline Hunyuan sur les images éditées

## Pièges connus (extrait CDC §3)

| Piège | Mitigation |
|---|---|
| `pip install torch` sans `--index-url` → wheel CPU, ~60× plus lent | install.bat utilise `--index-url https://download.pytorch.org/whl/cu124` |
| `deepspeed` / `bpy` | non requis par Kontext, ne pas installer |
| JSON éditeur ComfyUI ≠ JSON API | exporter via *Save (API Format)*, pas le format graphique |
| FLUX à `cfg=7` (SDXL-style) → rendu cramé | backend force `cfg=1.0` (constante `FLUX_CFG`) |
| Mélange env Python | toujours `conda activate kontext` |

## API

| Méthode | Route | Description |
|---|---|---|
| `GET` | `/` | page formulaire |
| `POST` | `/edit` | `images[]` (multipart) + `prompt` + `steps` + `guidance` + `seed` → `batch_id` |
| `GET` | `/status/{batch_id}` | état des jobs |
| `GET` | `/result/{batch_id}` | liste des résultats |
| `GET` | `/result/{batch_id}/{idx}` | télécharge l'image éditée |
