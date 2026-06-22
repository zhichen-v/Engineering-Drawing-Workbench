from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, Callable, Literal
from uuid import uuid4

import fitz
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from src import frame_detection


BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "test-ED"
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
STATIC_DIR = BASE_DIR / "static"
PREVIEW_SCALE = 2.0
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
OCR_TASKS: dict[str, dict[str, Any]] = {}
OCR_TASK_LOCK = Lock()

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


class FrameDetectionRequest(BaseModel):
    document: str
    page: int = Field(ge=1)
    load_id: str = Field(pattern=r"^\d{8}T\d{9}Z$")


class ExcelRequest(BaseModel):
    format: Literal["MIP", "QC"]


def build_job_path(document: str, load_id: str) -> tuple[str, Path]:
    document_stem = Path(document).stem
    safe_document_stem = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in document_stem
    ).strip("_") or "document"
    document_hash = hashlib.sha256(document.encode("utf-8")).hexdigest()[:8]
    job_id = f"{load_id}_{safe_document_stem}_{document_hash}"
    return job_id, OUTPUT_DIR / job_id


def get_pdf_path(document: str) -> Path:
    if Path(document).name != document:
        raise HTTPException(status_code=400, detail="Invalid document name")

    path = (UPLOAD_DIR if document.startswith("upload-") else PDF_DIR) / document
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


def run_ocr_job(
    job_dir: Path,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
) -> Path:
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
        ),
        progress_callback=progress_callback,
    )


def run_excel_job(job_dir: Path, output_format: Literal["MIP", "QC"]) -> dict[str, object]:
    script = BASE_DIR / "src" / "excel-method" / (
        "fill_MIP_all.py" if output_format == "MIP" else "fill_QC.py"
    )
    process = subprocess.run(
        [sys.executable, str(script), "--job", str(job_dir)],
        cwd=BASE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout).strip() or "Excel export failed")

    lines = [line for line in process.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Excel export returned no result")
    return json.loads(lines[-1])


def build_ocr_result(job_id: str, output_path: Path) -> dict[str, object]:
    result = json.loads(output_path.read_text(encoding="utf-8"))
    return {
        **result,
        "output_dir": f"output/{job_id}",
        "file": f"/output/{job_id}/ocr_results.json",
    }


def update_ocr_task(task_key: str, **updates: Any) -> dict[str, Any]:
    with OCR_TASK_LOCK:
        OCR_TASKS[task_key] = {**OCR_TASKS.get(task_key, {}), **updates}
        return deepcopy(OCR_TASKS[task_key])


def read_ocr_task(job_id: str, task_id: str) -> dict[str, Any]:
    with OCR_TASK_LOCK:
        task = OCR_TASKS.get(task_id)
        if not task or task.get("job_id") != job_id:
            raise HTTPException(status_code=404, detail="OCR task not found")
        return deepcopy(task)


def run_ocr_task(task_id: str, job_id: str, job_dir: Path) -> None:
    def report_progress(stage: str, details: dict[str, Any]) -> None:
        message = "載入 OCR 模型中" if stage == "model_loading" else "OCR 辨識中"
        update_ocr_task(
            task_id,
            status="running",
            stage=stage,
            message=message,
            **details,
        )

    try:
        output_path = run_ocr_job(job_dir, progress_callback=report_progress)
        update_ocr_task(
            task_id,
            status="completed",
            stage="completed",
            message="OCR 辨識完成",
            result=build_ocr_result(job_id, output_path),
        )
    except (FileNotFoundError, ValueError) as error:
        update_ocr_task(
            task_id,
            status="failed",
            stage="failed",
            message=str(error),
            error=str(error),
        )
    except Exception as error:
        update_ocr_task(
            task_id,
            status="failed",
            stage="failed",
            message=f"OCR failed: {error}",
            error=f"OCR failed: {error}",
        )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/documents/upload")
async def upload_document(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
) -> dict[str, int | str]:
    if Path(filename).name != filename or Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    UPLOAD_DIR.mkdir(exist_ok=True)
    document = f"upload-{uuid4().hex}.pdf"
    path = UPLOAD_DIR / document
    size = 0
    try:
        with path.open("wb") as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds 250 MB")
                target.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise

    try:
        with fitz.open(path) as pdf:
            pages = len(pdf)
            if pages < 1:
                raise ValueError("PDF has no pages")
    except Exception as error:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Invalid PDF file") from error

    # ponytail: one global upload; use per-user storage if concurrent users are added.
    for old_upload in UPLOAD_DIR.glob("upload-*.pdf"):
        if old_upload != path:
            old_upload.unlink()
    return {"id": document, "name": filename, "pages": pages, "source": "upload"}


@app.get("/api/documents/{document}/pages/{page_number}/preview")
def preview_page(
    document: str,
    page_number: int,
    scale: float = Query(PREVIEW_SCALE, ge=0.5, le=4),
) -> Response:
    return Response(render_page(document, page_number, scale), media_type="image/png")


@app.post("/api/frame-detection")
def detect_frame(request: FrameDetectionRequest) -> dict[str, object]:
    pdf_path = get_pdf_path(request.document)
    job_id, job_dir = build_job_path(request.document, request.load_id)
    job_dir.mkdir(exist_ok=True)

    with fitz.open(pdf_path) as pdf:
        if request.page < 1 or request.page > len(pdf):
            raise HTTPException(status_code=404, detail="Page not found")
        pages = list(range(1, len(pdf) + 1))
        images = {
            page_number: frame_detection.render_page_image(
                pdf[page_number - 1],
                PREVIEW_SCALE,
            )
            for page_number in pages
        }

    _, frame_result_path = frame_detection.write_job_frame_detection(
        request.document,
        pdf_path,
        pages,
        images,
        job_dir,
        PREVIEW_SCALE,
    )
    frame_result = json.loads(frame_result_path.read_text(encoding="utf-8"))
    overlays = {
        str(page_result["page"]): (
            f"/output/{job_id}/frame_detection/page_{int(page_result['page']):03d}/overlay.png"
        )
        for page_result in frame_result["pages"]
    }

    return {
        "job_id": job_id,
        "output_dir": f"output/{job_id}",
        "file": f"/output/{job_id}/{frame_result_path.relative_to(job_dir).as_posix()}",
        "overlays": overlays,
        "pages": frame_result["pages"],
        "scale": frame_result["scale"],
    }


@app.post("/api/jobs")
def create_job(request: JobRequest) -> dict[str, object]:
    if request.action == "crop" and not request.boxes:
        raise HTTPException(status_code=400, detail="At least one box is required for crop")
    box_ids = [box.id for box in request.boxes]
    if len(box_ids) != len(set(box_ids)):
        raise HTTPException(status_code=400, detail="Box IDs must be unique across pages")

    pdf_path = get_pdf_path(request.document)
    job_id, job_dir = build_job_path(request.document, request.load_id)
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
    except (FileNotFoundError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"OCR failed: {error}") from error

    return build_ocr_result(job_id, output_path)


@app.post("/api/jobs/{job_id}/ocr/tasks", status_code=202)
def start_ocr_task(job_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    job_dir = get_job_dir(job_id)
    task_id = uuid4().hex
    task = update_ocr_task(
        task_id,
        task_id=task_id,
        job_id=job_id,
        status="queued",
        stage="model_loading",
        message="載入 OCR 模型中",
        current=0,
        total=0,
    )
    background_tasks.add_task(run_ocr_task, task_id, job_id, job_dir)
    return task


@app.get("/api/jobs/{job_id}/ocr/tasks/{task_id}")
def get_ocr_task_status(job_id: str, task_id: str) -> dict[str, object]:
    get_job_dir(job_id)
    return read_ocr_task(job_id, task_id)


@app.post("/api/jobs/{job_id}/excel")
def export_job_excel(job_id: str, request: ExcelRequest) -> dict[str, object]:
    job_dir = get_job_dir(job_id)
    if not (job_dir / "ocr_results.json").is_file():
        raise HTTPException(status_code=400, detail="OCR results are required before Excel export")

    try:
        result = run_excel_job(job_dir, request.format)
    except (json.JSONDecodeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Excel export failed: {error}") from error

    output_dir = f"/output/{job_id}/excel-output/{request.format}"
    if request.format == "MIP":
        excel_file = f"{output_dir}/MIP_filled.xls"
        previews = [
            {"sheet": sheet, "file": f"{output_dir}/{sheet}_snapshot.png"}
            for sheet in ("MIP", "SUQC", "IPQC", "OGQC")
        ]
    else:
        excel_file = f"{output_dir}/QC_filled.xlsm"
        previews = [{"sheet": "OGQC", "file": f"{output_dir}/QC_snapshot.png"}]

    return {
        "format": request.format,
        "rows": result.get("rows", 0),
        "file": excel_file,
        "previews": previews,
    }
