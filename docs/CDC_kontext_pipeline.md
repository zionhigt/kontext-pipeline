# Cahier des charges — Intégration FLUX.1 Kontext [dev] dans le pipeline props JV

> Document destiné à Claude Code. Cible : machine Shadow, GPU RTX A4500 (20 Go VRAM), Windows.
> Rôle de ce module : étape de **prétraitement / édition d'image guidée par texte** en amont de la génération 3D Hunyuan. Exécution **séquentielle** sur le GPU (un seul modèle résident à la fois, jamais Kontext + Hunyuan simultanément).

---

## 1. Objectif

Fournir un service local d'édition d'image par instruction texte, exposé via une **interface web à formulaire**, permettant :

- le versement d'**une ou plusieurs images** (multi-upload) ;
- la saisie d'un **prompt texte** d'édition appliqué à chaque image ;
- la récupération des images éditées, destinées à alimenter ensuite Hunyuan3D.

Cas d'usage type : normalisation de pose (A-pose), nettoyage de fond, changement de matériau/usure, retrait d'éléments parasites — sans régénération complète, en préservant identité et géométrie.

Hors périmètre : la génération 3D elle-même (pipeline Hunyuan existant, non modifié ici).

---

## 2. Contraintes d'environnement (À RESPECTER)

| Élément | Valeur cible | Note |
|---|---|---|
| OS | Windows (natif, pas WSL) | exécution native Windows |
| Python | **3.10** | conda env dédié |
| CUDA toolkit | **12.4** | cohérent avec l'env Hunyuan existant |
| PyTorch | **2.6.0+cu124** | terrain connu (déjà utilisé pour Hunyuan) ; 2.7.0+cu124 acceptable en repli |
| Toolchain C++ | **MSVC v143 / cl.exe 14.34** (= VS 2022 **17.4**) | requise seulement si compilation de deps natives ; voir §2.1 |
| GPU | RTX A4500, 20 Go VRAM | exécution séquentielle dédiée |
| Variante modèle | **FP8 scaled (~12 Go)** | recommandé pour 20 Go ; full BF16 possible avec offload mais plus lent et risque OOM |

### 2.1 Toolchain de compilation (MSVC)

> La toolchain n'est nécessaire **que** si une dépendance doit être compilée nativement (build de wheel C++). Pour ComfyUI + Kontext en FP8 via wheels précompilés, elle ne devrait pas être sollicitée — mais la documenter par sécurité, vu les déboires passés sur des deps natives.
>
> Correspondance de versions (officielle Microsoft) :
> - **VS 2022 = 17.x** (numéro de version Visual Studio)
> - **v143** = nom du *platform toolset*, stable sur tout VS 2022
> - **cl.exe 14.34** = compilateur correspondant à **VS 2022 17.4** précisément
>
> Donc « 17.4 » et « 14.34 » désignent la même toolchain vue sous deux angles : c'est cohérent, ce n'est pas une version d'OS.
>
> Points d'attention :
> - Le toolset **v14.34-17.4 est marqué *Out of Support*** par Microsoft. Il compile encore, mais pour une install neuve préférer un **14.3x toujours supporté** (sélectionnable en Side-by-Side dans le VS Installer : *Modify → Individual components → MSVC v143 …*).
> - Depuis VS 2022 **17.10**, le compilateur est passé en **14.4x**, ce qui casse les checks de build supposant `_MSC_VER < 1940`. En restant sur 14.34 on n'est pas concerné ; si un build tiers réclame une toolchain plus récente, garder ce piège en tête.

Commande de contrôle (Developer Command Prompt) :

```bat
cl
```

Vérifier que la version affichée correspond bien à `19.34.x` (= cl.exe 14.34). Documenter la valeur réelle constatée dans le README d'install.

### 2.2 Vérifications d'environnement (à exécuter avant tout)

Dans l'env conda activé :

```bat
python --version
nvcc --version
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0)); print('bf16:', torch.cuda.is_bf16_supported())"
```

Critère de succès : `torch.cuda.is_available() == True` et device == "NVIDIA RTX A4500".

---

## 3. Leçons des intégrations précédentes (PIÈGES À ÉVITER)

1. **deepspeed / bpy** : sources d'échec lors d'installs antérieures (Hunyuan/Tencent).
   → **Kontext via ComfyUI n'en dépend PAS.** Ne PAS les installer. Si une dépendance tierce les réclame, traiter le besoin comme optionnel et le neutraliser (cf. méthode connue : commenter dans requirements, ou installer en `--no-build-isolation` seulement si réellement bloquant). **Par défaut : ne pas les toucher.**
2. **Wheel torch CPU par erreur** : `pip install torch` sans `--index-url` tire la version CPU sous Windows → générations ~60× plus lentes. **Toujours** passer `--index-url https://download.pytorch.org/whl/cu124`.
3. **Mélange de versions Python** : ne jamais lancer pip/python hors de l'env conda activé.
4. **JSON éditeur vs JSON API** : l'API HTTP `/prompt` attend l'export *Save (API Format)* (activer Dev Mode dans ComfyUI), pas le JSON de l'éditeur graphique.
5. **cfg FLUX** : FLUX tourne à **cfg = 1.0**. Ne pas copier un KSampler SDXL (cfg 7) → rendu cramé/saturé.

---

## 4. Architecture retenue

```
Front web (formulaire) -> Backend FastAPI -> ComfyUI daemon (FLUX.1 Kontext FP8)
```

Choix : **ComfyUI en daemon + backend FastAPI léger devant**, plutôt que diffusers brut. Raisons : pilotage headless scriptable via l'API ComfyUI, modèle gardé résident entre deux jobs (évite le rechargement des 12 Go), réutilisable par le reste du pipeline.

**Préférence outils tiers : privilégier les formes / distributions Windows-natives** (binaires Windows, custom nodes compatibles Windows) plutôt que des portages nécessitant un environnement POSIX.

---

## 5. Installation

### 5.1 Environnement conda

```bat
conda create -n kontext python=3.10 -y
conda activate kontext
python -m pip install --upgrade pip
```

### 5.2 ComfyUI + PyTorch

```bat
git clone https://github.com/comfyanonymous/ComfyUI
cd ComfyUI
pip install torch==2.6.0 torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
```

> Si torch 2.6.0+cu124 indisponible au wheel, replier sur 2.7.0+cu124 (même index-url). NE PAS retirer `--index-url`.

### 5.3 ComfyUI Manager (facultatif mais recommandé)

Installer ComfyUI-Manager pour gérer les custom nodes proprement (clone dans `custom_nodes/`).

### 5.4 Modèles (HuggingFace, licence à accepter)

Dépôt gated : `black-forest-labs/FLUX.1-Kontext-dev` (accepter la licence non-commerciale au préalable).

| Fichier | Destination |
|---|---|
| `flux1-kontext-dev` FP8 scaled (`.safetensors`) | `models/diffusion_models/` |
| `clip_l.safetensors` | `models/text_encoders/` |
| `t5xxl_fp8_e4m3fn.safetensors` | `models/text_encoders/` |
| `ae.safetensors` (VAE) | `models/vae/` |

> VAE, CLIP et text encoder sont **identiques** que l'on utilise la variante FP8 ou GGUF.

### 5.5 Lancement du daemon

```bat
python main.py --listen 127.0.0.1 --port 8188
```

> Pas de `--lowvram` requis a priori sur 20 Go avec FP8. À n'ajouter qu'en cas d'OOM constaté.

### 5.6 Backend + front

```bat
pip install fastapi uvicorn[standard] python-multipart pillow requests websocket-client
```

---

## 6. Spécification du backend (FastAPI)

### 6.1 Endpoints

| Méthode | Route | Rôle |
|---|---|---|
| `GET` | `/` | sert la page formulaire |
| `POST` | `/edit` | reçoit `images[]` (multipart) + `prompt` + params ; lance les jobs ; renvoie un `batch_id` |
| `GET` | `/status/{batch_id}` | état d'avancement (queue/running/done par image) |
| `GET` | `/result/{batch_id}` | liste des images éditées (URLs ou base64) |
| `GET` | `/result/{batch_id}/{idx}` | télécharge une image précise |

### 6.2 Paramètres d'édition exposés au formulaire

- `prompt` (texte, requis) — instruction d'édition appliquée à toutes les images du batch.
- `steps` (défaut 20–28)
- `guidance` (défaut **2.5**) — cohérent avec l'usage Kontext.
- `seed` (entier ; option « aléatoire »)
- `cfg` **forcé à 1.0 côté backend** (non éditable, cf. §3.5).

### 6.3 Logique de traitement

1. Sauver chaque image uploadée dans un dossier de batch horodaté.
2. Pour chaque image : charger le **template de workflow JSON (API format)**, injecter le chemin image + prompt + params.
3. `POST /prompt` vers ComfyUI ; récupérer le `prompt_id`.
4. Poller `GET /history/{prompt_id}` jusqu'à complétion (ou écoute WebSocket `/ws` pour la progression).
5. Récupérer l'image de sortie via `/view` (filename/subfolder/type retournés dans l'historique).
6. Exposer les résultats au front.

> Exécution **séquentielle** : traiter les images d'un batch une par une (file d'attente ComfyUI native). Ne pas paralléliser sur GPU.

### 6.4 Template de workflow

- Exporter depuis ComfyUI un workflow Kontext minimal : *Load Image → (CLIP/T5 encode) → Kontext → VAE decode → Save Image*, en **Save (API Format)**.
- Stocker ce JSON comme template ; le backend remplit dynamiquement : node LoadImage (chemin), node prompt (texte), KSampler (steps/seed/guidance, cfg=1.0).
- Documenter les **IDs de nodes** à patcher (ils dépendent de l'export ; ne pas coder en dur sans vérifier).

---

## 7. Spécification du front (formulaire web)

- Page unique servie par FastAPI.
- Zone de dépôt **multi-fichiers** (drag & drop + sélecteur), aperçu des vignettes avant envoi.
- Champ `prompt` (textarea) + champs paramètres (steps, guidance, seed).
- Bouton « Lancer l'édition » → POST `/edit`.
- Affichage de la progression (polling `/status`).
- Galerie résultats avant/après, bouton de téléchargement individuel et « tout télécharger ».
- Stack libre mais simple (HTML + JS vanilla ou un front léger) — pas de dépendance lourde imposée.

---

## 8. Gestion VRAM / séquencement avec Hunyuan

- Kontext (FP8 ~12 Go) et Hunyuan ne tournent **jamais en même temps**.
- Workflow opérateur : (1) lancer le daemon Kontext, éditer le batch d'images, (2) arrêter le daemon Kontext pour libérer la VRAM, (3) lancer le pipeline Hunyuan sur les images éditées.
- Prévoir un script d'arrêt propre du daemon ComfyUI (libération VRAM vérifiable via `nvidia-smi`).
- Option d'optimisation ultérieure (non requise) : variante GGUF Q4/Q5 si l'on souhaite un jour cohabiter avec un autre modèle — hors périmètre actuel.

---

## 9. Critères d'acceptation

- [ ] Env conda `kontext` créé, Python 3.10, torch 2.6.0+cu124, CUDA visible sur A4500.
- [ ] Aucune installation de deepspeed ni bpy.
- [ ] ComfyUI démarre en daemon, modèle Kontext FP8 chargé sans OOM.
- [ ] Front : upload de N images + 1 prompt → N images éditées récupérables.
- [ ] cfg=1.0 effectif (rendu non saturé).
- [ ] Workflow soumis en API format (pas le JSON éditeur).
- [ ] Arrêt propre du daemon → VRAM libérée pour Hunyuan (vérifié `nvidia-smi`).
- [ ] README d'install documentant la version `cl.exe` constatée (toolchain MSVC), si compilation native sollicitée.

---

## 10. Livrables

1. Script/instructions d'install (`.bat` ou README) reproductibles.
2. Daemon ComfyUI configuré + modèles en place.
3. Backend FastAPI (`app.py` + template workflow JSON).
4. Front formulaire (page + assets).
5. Script d'arrêt propre du daemon.
6. README : prérequis, versions constatées, lancement, séquençage avec Hunyuan, pièges connus.
