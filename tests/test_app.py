import json
from pathlib import Path

import fitz
from fastapi.testclient import TestClient
from PIL import Image

import app as app_module


def create_test_pdf(path, pages=1, frame_grid=False):
    pdf = fitz.open()
    for page_number in range(1, pages + 1):
        page = pdf.new_page(
            width=400 if frame_grid else 100,
            height=300 if frame_grid else 80,
        )
        page.insert_text((10, 20), f"TEST DRAWING {page_number}")
        if frame_grid:
            for label, x in zip(("1", "2", "3", "4"), (50, 150, 250, 350)):
                page.insert_text((x, 10), label)
                page.insert_text((x, 296), label)
            for label, y in zip(("A", "B", "C", "D"), (50, 115, 185, 250)):
                page.insert_text((4, y), label)
                page.insert_text((390, y), label)
            page.draw_rect(fitz.Rect(15, 15, 385, 285))
    pdf.save(path)
    pdf.close()


def test_root_serves_react_build():
    client = TestClient(app_module.app)
    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/static/assets/" in response.text


def test_preview_and_crop_job(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "test-ED"
    output_dir = tmp_path / "output"
    pdf_dir.mkdir()
    output_dir.mkdir()
    create_test_pdf(pdf_dir / "drawing.pdf")

    monkeypatch.setattr(app_module, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    client = TestClient(app_module.app)

    documents = client.get("/api/documents")
    assert documents.status_code == 200
    assert documents.json() == [{"name": "drawing.pdf", "pages": 1}]

    preview = client.get("/api/documents/drawing.pdf/pages/1/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"

    response = client.post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260615T120000000Z",
            "action": "crop",
            "boxes": [{"id": 1, "x": 10, "y": 12, "width": 30, "height": 24}],
        },
    )
    assert response.status_code == 200

    job_dir = output_dir / response.json()["job_id"]
    assert (job_dir / "snapshot_page_001.png").is_file()
    assert (job_dir / "crop_001.png").is_file()
    assert (job_dir / "boxes.json").is_file()

    with Image.open(job_dir / "crop_001.png") as crop:
        assert crop.size == (30, 24)

    metadata = json.loads((job_dir / "boxes.json").read_text(encoding="utf-8"))
    assert metadata["document"] == "drawing.pdf"
    assert metadata["boxes"] == [
        {
            "id": 1,
            "page": 1,
            "x": 10,
            "y": 12,
            "width": 30,
            "height": 24,
            "frame_location": None,
        }
    ]
    assert (job_dir / "frame_detection" / "frame_detection_results.json").is_file()


def test_repeated_crop_updates_same_output_by_box_id(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "test-ED"
    output_dir = tmp_path / "output"
    pdf_dir.mkdir()
    output_dir.mkdir()
    create_test_pdf(pdf_dir / "drawing.pdf")

    monkeypatch.setattr(app_module, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    client = TestClient(app_module.app)
    first = client.post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260615T120000000Z",
            "action": "crop",
            "boxes": [
                {"id": 1, "x": 10, "y": 12, "width": 30, "height": 24},
                {"id": 2, "x": 20, "y": 24, "width": 40, "height": 32},
            ],
        },
    )
    second = client.post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260615T120000000Z",
            "action": "crop",
            "boxes": [{"id": 2, "x": 30, "y": 36, "width": 50, "height": 40}],
        },
    )
    saved = client.post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260615T120000000Z",
            "action": "save",
            "boxes": [{"id": 2, "x": 30, "y": 36, "width": 50, "height": 40}],
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert saved.status_code == 200
    assert second.json()["job_id"] == first.json()["job_id"]
    assert saved.json()["job_id"] == first.json()["job_id"]
    assert len(list(output_dir.iterdir())) == 1

    job_dir = output_dir / second.json()["job_id"]
    assert not (job_dir / "crop_001.png").exists()
    assert (job_dir / "crop_002.png").is_file()

    with Image.open(job_dir / "crop_002.png") as crop:
        assert crop.size == (50, 40)

    metadata = json.loads((job_dir / "boxes.json").read_text(encoding="utf-8"))
    assert metadata["boxes"] == [
        {
            "id": 2,
            "page": 1,
            "x": 30,
            "y": 36,
            "width": 50,
            "height": 40,
            "frame_location": None,
        }
    ]


def test_pages_share_one_output_and_global_crop_numbers(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "test-ED"
    output_dir = tmp_path / "output"
    pdf_dir.mkdir()
    output_dir.mkdir()
    create_test_pdf(pdf_dir / "drawing.pdf", pages=2)

    monkeypatch.setattr(app_module, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    response = TestClient(app_module.app).post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 2,
            "load_id": "20260615T120000000Z",
            "action": "crop",
            "boxes": [
                {"id": 1, "page": 1, "x": 10, "y": 12, "width": 30, "height": 24},
                {"id": 2, "page": 2, "x": 20, "y": 22, "width": 40, "height": 30},
            ],
        },
    )

    assert response.status_code == 200
    assert "_page_" not in response.json()["job_id"]
    job_dir = output_dir / response.json()["job_id"]
    assert (job_dir / "snapshot_page_001.png").is_file()
    assert (job_dir / "snapshot_page_002.png").is_file()
    assert (job_dir / "crop_001.png").is_file()
    assert (job_dir / "crop_002.png").is_file()

    metadata = json.loads((job_dir / "boxes.json").read_text(encoding="utf-8"))
    assert metadata["pages"] == [1, 2]
    assert [box["page"] for box in metadata["boxes"]] == [1, 2]


def test_crop_job_writes_frame_detection_and_frame_location(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "test-ED"
    output_dir = tmp_path / "output"
    pdf_dir.mkdir()
    output_dir.mkdir()
    create_test_pdf(pdf_dir / "drawing.pdf", frame_grid=True)

    monkeypatch.setattr(app_module, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    response = TestClient(app_module.app).post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260616T034640664Z",
            "action": "crop",
            "boxes": [{"id": 1, "x": 480, "y": 480, "width": 40, "height": 30}],
        },
    )

    assert response.status_code == 200
    job_dir = output_dir / response.json()["job_id"]
    frame_result_path = job_dir / "frame_detection" / "frame_detection_results.json"
    assert frame_result_path.is_file()

    metadata = json.loads((job_dir / "boxes.json").read_text(encoding="utf-8"))
    assert metadata["boxes"][0]["frame_location"] == "D3"

    frame_result = json.loads(frame_result_path.read_text(encoding="utf-8"))
    assert frame_result["pages"][0]["source"] == "pdf_text"


def test_frame_detection_endpoint_writes_overlay_for_frontend(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "test-ED"
    output_dir = tmp_path / "output"
    pdf_dir.mkdir()
    output_dir.mkdir()
    create_test_pdf(pdf_dir / "drawing.pdf", pages=3)

    monkeypatch.setattr(app_module, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    client = TestClient(app_module.app)
    response = client.post(
        "/api/frame-detection",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260617T040045193Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    job_dir = output_dir / payload["job_id"]
    assert payload["output_dir"] == f"output/{payload['job_id']}"
    assert payload["file"] == f"/output/{payload['job_id']}/frame_detection/frame_detection_results.json"
    assert sorted(payload["overlays"]) == ["1", "2", "3"]
    for page_number in range(1, 4):
        assert payload["overlays"][str(page_number)] == (
            f"/output/{payload['job_id']}/frame_detection/page_{page_number:03d}/overlay.png"
        )
        assert (
            job_dir / "frame_detection" / f"page_{page_number:03d}" / "overlay.png"
        ).is_file()

    saved = client.post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
            "load_id": "20260617T040045193Z",
            "action": "save",
            "boxes": [{"id": 1, "page": 1, "x": 10, "y": 12, "width": 30, "height": 24}],
        },
    )

    assert saved.status_code == 200
    frame_result = json.loads(
        (job_dir / "frame_detection" / "frame_detection_results.json").read_text(
            encoding="utf-8"
        )
    )
    assert [page["page"] for page in frame_result["pages"]] == [1, 2, 3]
    assert (job_dir / "frame_detection" / "page_002" / "overlay.png").is_file()
    assert (job_dir / "frame_detection" / "page_003" / "overlay.png").is_file()


def test_different_loads_create_separate_time_ordered_outputs(tmp_path, monkeypatch):
    pdf_dir = tmp_path / "test-ED"
    output_dir = tmp_path / "output"
    pdf_dir.mkdir()
    output_dir.mkdir()
    create_test_pdf(pdf_dir / "drawing.pdf")

    monkeypatch.setattr(app_module, "PDF_DIR", pdf_dir)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    client = TestClient(app_module.app)
    payload = {
        "document": "drawing.pdf",
        "page": 1,
        "action": "crop",
        "boxes": [{"id": 1, "x": 10, "y": 12, "width": 30, "height": 24}],
    }
    first = client.post("/api/jobs", json={**payload, "load_id": "20260615T120000000Z"})
    second = client.post("/api/jobs", json={**payload, "load_id": "20260615T120100000Z"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] != second.json()["job_id"]
    assert sorted(path.name for path in output_dir.iterdir()) == [
        first.json()["job_id"],
        second.json()["job_id"],
    ]


def test_crop_requires_a_box():
    client = TestClient(app_module.app)
    response = client.post(
        "/api/jobs",
        json={
            "document": "missing.pdf",
            "page": 1,
            "load_id": "20260615T120000000Z",
            "action": "crop",
            "boxes": [],
        },
    )
    assert response.status_code == 400


def test_recognize_job_returns_ocr_results(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    job_dir = output_dir / "20260615T120000000Z_drawing"
    job_dir.mkdir(parents=True)

    def fake_run_ocr_job(target):
        assert target == job_dir
        result_path = target / "ocr_results.json"
        result_path.write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "results": [
                        {
                            "crop_number": 1,
                            "box": {
                                "id": 1,
                                "x": 10,
                                "y": 12,
                                "width": 30,
                                "height": 24,
                                "frame_location": "D3",
                            },
                            "ocr": "⌀ 0.5",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return result_path

    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(app_module, "run_ocr_job", fake_run_ocr_job)

    response = TestClient(app_module.app).post(f"/api/jobs/{job_dir.name}/ocr")

    assert response.status_code == 200
    assert response.json()["results"][0]["ocr"] == "⌀ 0.5"
    assert response.json()["file"] == f"/output/{job_dir.name}/ocr_results.json"


def test_ocr_task_reports_progress_and_result(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    job_dir = output_dir / "20260615T120000000Z_drawing"
    job_dir.mkdir(parents=True)

    def fake_run_ocr_job(target, progress_callback=None):
        assert target == job_dir
        assert progress_callback is not None
        progress_callback("model_loading", {"current": 0, "total": 1})
        progress_callback("recognizing", {"current": 1, "total": 1, "crop": "crop_001.png"})
        result_path = target / "ocr_results.json"
        result_path.write_text(
            json.dumps(
                {
                    "job_id": job_dir.name,
                    "results": [{"crop_number": 1, "box": {"id": 1}, "ocr": "0.5"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return result_path

    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(app_module, "run_ocr_job", fake_run_ocr_job)

    client = TestClient(app_module.app)
    response = client.post(f"/api/jobs/{job_dir.name}/ocr/tasks")

    assert response.status_code == 202
    started = response.json()
    assert started["stage"] == "model_loading"

    status = client.get(f"/api/jobs/{job_dir.name}/ocr/tasks/{started['task_id']}")
    assert status.status_code == 200
    payload = status.json()
    assert payload["status"] == "completed"
    assert payload["result"]["results"][0]["ocr"] == "0.5"
    assert payload["result"]["file"] == f"/output/{job_dir.name}/ocr_results.json"


def test_recognize_job_requires_existing_job(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")

    response = TestClient(app_module.app).post("/api/jobs/missing/ocr")

    assert response.status_code == 404


def test_export_job_excel_returns_preview_and_download_urls(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    job_dir = output_dir / "20260615T120000000Z_drawing"
    job_dir.mkdir(parents=True)
    (job_dir / "ocr_results.json").write_text('{"results": []}', encoding="utf-8")

    def fake_run_excel_job(target, output_format):
        assert target == job_dir
        assert output_format == "MIP"
        return {"status": "success", "rows": 12}

    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(app_module, "run_excel_job", fake_run_excel_job)

    response = TestClient(app_module.app).post(
        f"/api/jobs/{job_dir.name}/excel",
        json={"format": "MIP"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "format": "MIP",
        "rows": 12,
        "file": f"/output/{job_dir.name}/excel-output/MIP/MIP_filled.xls",
        "previews": [
            {
                "sheet": sheet,
                "file": f"/output/{job_dir.name}/excel-output/MIP/{sheet}_snapshot.png",
            }
            for sheet in ("MIP", "SUQC", "IPQC", "OGQC")
        ],
    }


def test_export_job_excel_requires_ocr_results(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    job_dir = output_dir / "20260615T120000000Z_drawing"
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(app_module, "OUTPUT_DIR", output_dir)

    response = TestClient(app_module.app).post(
        f"/api/jobs/{job_dir.name}/excel",
        json={"format": "QC"},
    )

    assert response.status_code == 400
