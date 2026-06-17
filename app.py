from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import fitz
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from src import frame_detection


BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "test-ED"
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
PREVIEW_SCALE = 2.0

OUTPUT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="ED Crop Workbench")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")


class Box(BaseModel):
    id: int = Field(ge=1)
    page: int | None = Field(default=None, ge=1)
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class JobRequest(BaseModel):
    document: str
    page: int = Field(ge=1)
    load_id: str = Field(pattern=r"^\d{8}T\d{9}Z$")
    boxes: list[Box]
    action: Literal["save", "crop"]


def get_pdf_path(document: str) -> Path:
    if Path(document).name != document:
        raise HTTPException(status_code=400, detail="Invalid document name")

    path = PDF_DIR / document
    if path.suffix.lower() != ".pdf" or not path.is_file():
        raise HTTPException(status_code=404, detail="PDF not found")
    return path


def render_page(document: str, page_number: int, scale: float = PREVIEW_SCALE) -> bytes:
    path = get_pdf_path(document)
    with fitz.open(path) as pdf:
        if page_number < 1 or page_number > len(pdf):
            raise HTTPException(status_code=404, detail="Page not found")
        pixmap = pdf[page_number - 1].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        return pixmap.tobytes("png")


def get_job_dir(job_id: str) -> Path:
    if Path(job_id).name != job_id:
        raise HTTPException(status_code=400, detail="Invalid job ID")

    job_dir = OUTPUT_DIR / job_id
    if not job_dir.is_dir():
        raise HTTPException(status_code=404, detail="Job not found")
    return job_dir


def run_ocr_job(job_dir: Path) -> Path:
    from src import ocr

    return ocr.run_ocr(
        SimpleNamespace(
            input_dir=job_dir,
            classifier_checkpoint=ocr.CLASSIFIER_CHECKPOINT,
            classifier_threshold=0.4,
            diameter_threshold=0.99,
            device="auto",
            max_new_tokens=128,
            allow_model_download=False,
        )
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/documents")
def list_documents() -> list[dict[str, int | str]]:
    documents = []
    for path in sorted(PDF_DIR.glob("*.pdf")):
        with fitz.open(path) as pdf:
            documents.append({"name": path.name, "pages": len(pdf)})
    return documents


@app.get("/api/documents/{document}/pages/{page_number}/preview")
def preview_page(
    document: str,
    page_number: int,
    scale: float = Query(PREVIEW_SCALE, ge=0.5, le=4),
) -> Response:
    return Response(render_page(document, page_number, scale), media_type="image/png")


@app.post("/api/jobs")
def create_job(request: JobRequest) -> dict[str, object]:
    if request.action == "crop" and not request.boxes:
        raise HTTPException(status_code=400, detail="At least one box is required for crop")
    box_ids = [box.id for box in request.boxes]
    if len(box_ids) != len(set(box_ids)):
        raise HTTPException(status_code=400, detail="Box IDs must be unique across pages")

    pdf_path = get_pdf_path(request.document)
    document_stem = Path(request.document).stem
    safe_document_stem = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in document_stem
    ).strip("_") or "document"
    document_hash = hashlib.sha256(request.document.encode("utf-8")).hexdigest()[:8]
    job_id = f"{request.load_id}_{safe_document_stem}_{document_hash}"
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    if request.action == "crop":
        for crop_path in job_dir.glob("crop_*.png"):
            crop_path.unlink()
        for snapshot_path in job_dir.glob("snapshot_page_*.png"):
            snapshot_path.unlink()

    pages = sorted({box.page or request.page for box in request.boxes} or {request.page})
    images = {}
    snapshots = {}
    result_files = []
    for page_number in pages:
        snapshot = render_page(request.document, page_number)
        image = Image.open(io.BytesIO(snapshot))
        snapshot_name = f"snapshot_page_{page_number:03d}.png"
        (job_dir / snapshot_name).write_bytes(snapshot)
        images[page_number] = image
        snapshots[str(page_number)] = {"width": image.width, "height": image.height}
        result_files.append(f"/output/{job_id}/{snapshot_name}")

    frame_grids, frame_result_path = frame_detection.write_job_frame_detection(
        request.document,
        pdf_path,
        pages,
        images,
        job_dir,
        PREVIEW_SCALE,
    )
    result_files.append(f"/output/{job_id}/{frame_result_path.relative_to(job_dir).as_posix()}")

    saved_boxes = []
    for box in request.boxes:
        page_number = box.page or request.page
        image = images[page_number]
        left = max(0, min(round(box.x), image.width - 1))
        top = max(0, min(round(box.y), image.height - 1))
        right = max(left + 1, min(round(box.x + box.width), image.width))
        bottom = max(top + 1, min(round(box.y + box.height), image.height))

        saved_box = {
            "id": box.id,
            "page": page_number,
            "x": left,
            "y": top,
            "width": right - left,
            "height": bottom - top,
        }
        saved_box["frame_location"] = frame_detection.locate_box(
            frame_grids.get(page_number),
            saved_box,
        )
        saved_boxes.append(saved_box)

        if request.action == "crop":
            crop_name = f"crop_{box.id:03d}.png"
            image.crop((left, top, right, bottom)).save(job_dir / crop_name)
            result_files.append(f"/output/{job_id}/{crop_name}")

    metadata = {
        "job_id": job_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "load_id": request.load_id,
        "action": request.action,
        "document": request.document,
        "pages": pages,
        "snapshots": snapshots,
        "boxes": saved_boxes,
    }
    (job_dir / "boxes.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result_files.append(f"/output/{job_id}/boxes.json")

    return {
        "job_id": job_id,
        "output_dir": f"output/{job_id}",
        "files": result_files,
    }


@app.post("/api/jobs/{job_id}/ocr")
def recognize_job(job_id: str) -> dict[str, object]:
    job_dir = get_job_dir(job_id)
    try:
        output_path = run_ocr_job(job_dir)
        result = json.loads(output_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"OCR failed: {error}") from error

    return {
        **result,
        "output_dir": f"output/{job_id}",
        "file": f"/output/{job_id}/ocr_results.json",
    }
