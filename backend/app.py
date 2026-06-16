"""
Backend FastAPI — proxy d'édition d'image via FLUX.1 Kontext (ComfyUI).

Endpoints (cf. CDC §6.1) :
  GET  /                        page formulaire
  POST /edit                    images[] + prompt + params -> batch_id
  GET  /status/{batch_id}       avancement par image
  GET  /result/{batch_id}       liste des résultats
  GET  /result/{batch_id}/{idx} télécharge une image éditée

Le backend est un client de ComfyUI (daemon localhost:8188). Il ne charge
aucun modèle lui-même : il construit un workflow JSON (API format),
le poste à ComfyUI, puis poll /history jusqu'à complétion.
"""

from __future__ import annotations

import copy
import json
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ------------------------------------------------------------------ config

ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT / "frontend"
WORKFLOW_TEMPLATE = ROOT / "workflows" / "kontext_api_template.json"
BATCH_ROOT = ROOT / "data" / "batches"
BATCH_ROOT.mkdir(parents=True, exist_ok=True)

COMFY_HOST = os.environ.get("COMFY_HOST", "127.0.0.1")
COMFY_PORT = int(os.environ.get("COMFY_PORT", "8188"))
COMFY_BASE = f"http://{COMFY_HOST}:{COMFY_PORT}"

# IDs de nodes à patcher dans le template (cf. CDC §6.4 : à vérifier
# manuellement lors de l'export Save (API Format) depuis ComfyUI).
NODE_LOAD_IMAGE = "LOAD_IMAGE"
NODE_PROMPT_TEXT = "PROMPT_TEXT"
NODE_KSAMPLER = "KSAMPLER"
NODE_FLUX_GUIDANCE = "FLUX_GUIDANCE"

# cfg FLUX forcé à 1.0 (cf. CDC §3.5).
FLUX_CFG = 1.0


# ------------------------------------------------------------------ state

@dataclass
class ImageJob:
    idx: int
    src_path: Path
    prompt_id: str | None = None
    state: str = "queued"          # queued | running | done | error
    output_path: Path | None = None
    error: str | None = None


@dataclass
class Batch:
    batch_id: str
    dir: Path
    prompt: str
    steps: int
    guidance: float
    seed: int
    jobs: list[ImageJob] = field(default_factory=list)


BATCHES: dict[str, Batch] = {}
BATCHES_LOCK = threading.Lock()


# ------------------------------------------------------------------ workflow

def load_template() -> dict[str, Any]:
    if not WORKFLOW_TEMPLATE.exists():
        raise RuntimeError(
            f"Template workflow introuvable : {WORKFLOW_TEMPLATE}. "
            "Exporter un workflow Kontext depuis ComfyUI en Save (API Format) "
            "et le placer à cet emplacement."
        )
    return json.loads(WORKFLOW_TEMPLATE.read_text(encoding="utf-8"))


def patch_workflow(
    template: dict[str, Any],
    image_filename: str,
    prompt: str,
    steps: int,
    guidance: float,
    seed: int,
) -> dict[str, Any]:
    """Injecte image/prompt/params dans le template. cfg forcé à 1.0."""
    wf = copy.deepcopy(template)

    def _node(node_id: str) -> dict[str, Any]:
        if node_id not in wf:
            raise RuntimeError(
                f"Node '{node_id}' absent du template. Réexporter le workflow "
                "et ajuster les constantes NODE_* dans backend/app.py."
            )
        return wf[node_id]

    _node(NODE_LOAD_IMAGE)["inputs"]["image"] = image_filename
    _node(NODE_PROMPT_TEXT)["inputs"]["text"] = prompt

    ks = _node(NODE_KSAMPLER)["inputs"]
    ks["steps"] = steps
    ks["seed"] = seed
    ks["cfg"] = FLUX_CFG

    _node(NODE_FLUX_GUIDANCE)["inputs"]["guidance"] = guidance
    return wf


# ------------------------------------------------------------------ ComfyUI

def comfy_upload_image(path: Path) -> str:
    """Upload une image dans le input/ de ComfyUI, renvoie le nom de fichier."""
    with path.open("rb") as fh:
        r = requests.post(
            f"{COMFY_BASE}/upload/image",
            files={"image": (path.name, fh, "image/png")},
            data={"overwrite": "true"},
            timeout=60,
        )
    r.raise_for_status()
    return r.json()["name"]


def comfy_queue(workflow: dict[str, Any]) -> str:
    r = requests.post(
        f"{COMFY_BASE}/prompt",
        json={"prompt": workflow, "client_id": "kontext-pipeline"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["prompt_id"]


def comfy_history(prompt_id: str) -> dict[str, Any] | None:
    r = requests.get(f"{COMFY_BASE}/history/{prompt_id}", timeout=10)
    r.raise_for_status()
    data = r.json()
    return data.get(prompt_id)


def comfy_view(filename: str, subfolder: str, type_: str) -> bytes:
    r = requests.get(
        f"{COMFY_BASE}/view",
        params={"filename": filename, "subfolder": subfolder, "type": type_},
        timeout=60,
    )
    r.raise_for_status()
    return r.content


# ------------------------------------------------------------------ worker

def run_batch(batch_id: str) -> None:
    """Traite les jobs d'un batch en séquence (un seul job ComfyUI à la fois)."""
    with BATCHES_LOCK:
        batch = BATCHES[batch_id]

    template = load_template()

    for job in batch.jobs:
        try:
            job.state = "running"
            comfy_name = comfy_upload_image(job.src_path)
            wf = patch_workflow(
                template,
                image_filename=comfy_name,
                prompt=batch.prompt,
                steps=batch.steps,
                guidance=batch.guidance,
                seed=batch.seed,
            )
            job.prompt_id = comfy_queue(wf)

            # Polling /history. ComfyUI n'expose pas de timeout côté serveur ;
            # on cap localement à 10 min par image pour éviter un hang infini.
            deadline = time.time() + 600
            while time.time() < deadline:
                hist = comfy_history(job.prompt_id)
                if hist and "outputs" in hist:
                    break
                time.sleep(1.0)
            else:
                raise TimeoutError("ComfyUI a dépassé 600 s sur ce job")

            outputs = hist["outputs"]
            # Récupère la première image émise par n'importe quel node de sortie.
            img_meta = None
            for node_out in outputs.values():
                if "images" in node_out and node_out["images"]:
                    img_meta = node_out["images"][0]
                    break
            if img_meta is None:
                raise RuntimeError("Aucune image en sortie")

            content = comfy_view(
                img_meta["filename"],
                img_meta.get("subfolder", ""),
                img_meta.get("type", "output"),
            )
            out_path = batch.dir / f"out_{job.idx:03d}_{img_meta['filename']}"
            out_path.write_bytes(content)
            job.output_path = out_path
            job.state = "done"
        except Exception as exc:                                     # noqa: BLE001
            job.state = "error"
            job.error = str(exc)


# ------------------------------------------------------------------ FastAPI

app = FastAPI(title="Kontext Pipeline")

if (FRONTEND_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.post("/edit")
async def edit(
    background: BackgroundTasks,
    prompt: str = Form(...),
    steps: int = Form(24),
    guidance: float = Form(2.5),
    seed: int = Form(-1),
    images: list[UploadFile] = File(...),
) -> JSONResponse:
    if not images:
        raise HTTPException(400, "Au moins une image est requise")
    if seed < 0:
        seed = random.randint(0, 2**31 - 1)

    batch_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    batch_dir = BATCH_ROOT / batch_id
    (batch_dir / "in").mkdir(parents=True, exist_ok=True)

    jobs: list[ImageJob] = []
    for i, up in enumerate(images):
        suffix = Path(up.filename or f"img_{i}.png").suffix or ".png"
        dst = batch_dir / "in" / f"img_{i:03d}{suffix}"
        dst.write_bytes(await up.read())
        jobs.append(ImageJob(idx=i, src_path=dst))

    batch = Batch(
        batch_id=batch_id,
        dir=batch_dir,
        prompt=prompt,
        steps=steps,
        guidance=guidance,
        seed=seed,
        jobs=jobs,
    )
    with BATCHES_LOCK:
        BATCHES[batch_id] = batch

    background.add_task(run_batch, batch_id)
    return JSONResponse({"batch_id": batch_id, "count": len(jobs), "seed": seed})


@app.get("/status/{batch_id}")
def status(batch_id: str) -> JSONResponse:
    with BATCHES_LOCK:
        batch = BATCHES.get(batch_id)
    if batch is None:
        raise HTTPException(404, "batch inconnu")
    return JSONResponse({
        "batch_id": batch_id,
        "jobs": [
            {"idx": j.idx, "state": j.state, "error": j.error}
            for j in batch.jobs
        ],
    })


@app.get("/result/{batch_id}")
def result_list(batch_id: str) -> JSONResponse:
    with BATCHES_LOCK:
        batch = BATCHES.get(batch_id)
    if batch is None:
        raise HTTPException(404, "batch inconnu")
    return JSONResponse({
        "batch_id": batch_id,
        "results": [
            {
                "idx": j.idx,
                "state": j.state,
                "url": f"/result/{batch_id}/{j.idx}" if j.state == "done" else None,
            }
            for j in batch.jobs
        ],
    })


@app.get("/result/{batch_id}/{idx}")
def result_one(batch_id: str, idx: int) -> FileResponse:
    with BATCHES_LOCK:
        batch = BATCHES.get(batch_id)
    if batch is None or idx >= len(batch.jobs):
        raise HTTPException(404, "introuvable")
    job = batch.jobs[idx]
    if job.state != "done" or job.output_path is None:
        raise HTTPException(409, f"image non prête (état={job.state})")
    return FileResponse(job.output_path, media_type="image/png", filename=job.output_path.name)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
