from __future__ import annotations

import io
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Literal

import fitz
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field


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
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class JobRequest(BaseModel):
    document: str
    page: int = Field(ge=1)
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

    snapshot = render_page(request.document, request.page)
    image = Image.open(io.BytesIO(snapshot))

    job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{secrets.token_hex(4)}"
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir()
    (job_dir / "snapshot.png").write_bytes(snapshot)

    saved_boxes = []
    result_files = [f"/output/{job_id}/snapshot.png"]
    for index, box in enumerate(request.boxes, start=1):
        left = max(0, min(round(box.x), image.width - 1))
        top = max(0, min(round(box.y), image.height - 1))
        right = max(left + 1, min(round(box.x + box.width), image.width))
        bottom = max(top + 1, min(round(box.y + box.height), image.height))

        saved_boxes.append(
            {
                "id": index,
                "x": left,
                "y": top,
                "width": right - left,
                "height": bottom - top,
            }
        )

        if request.action == "crop":
            crop_name = f"crop_{index:03d}.png"
            image.crop((left, top, right, bottom)).save(job_dir / crop_name)
            result_files.append(f"/output/{job_id}/{crop_name}")

    metadata = {
        "job_id": job_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": request.action,
        "document": request.document,
        "page": request.page,
        "snapshot": {"width": image.width, "height": image.height},
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
