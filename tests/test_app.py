import json

import fitz
from fastapi.testclient import TestClient
from PIL import Image

import app as app_module


def create_test_pdf(path, pages=1):
    pdf = fitz.open()
    for page_number in range(1, pages + 1):
        page = pdf.new_page(width=100, height=80)
        page.insert_text((10, 20), f"TEST DRAWING {page_number}")
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
    assert metadata["boxes"] == [{"id": 1, "page": 1, "x": 10, "y": 12, "width": 30, "height": 24}]


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
    assert metadata["boxes"] == [{"id": 2, "page": 1, "x": 30, "y": 36, "width": 50, "height": 40}]


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
                            "box": {"id": 1, "x": 10, "y": 12, "width": 30, "height": 24},
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


def test_recognize_job_requires_existing_job(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", tmp_path / "output")

    response = TestClient(app_module.app).post("/api/jobs/missing/ocr")

    assert response.status_code == 404
