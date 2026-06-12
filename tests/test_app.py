import json

import fitz
from fastapi.testclient import TestClient
from PIL import Image

import app as app_module


def create_test_pdf(path):
    pdf = fitz.open()
    page = pdf.new_page(width=100, height=80)
    page.insert_text((10, 20), "TEST DRAWING")
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
            "action": "crop",
            "boxes": [{"id": 1, "x": 10, "y": 12, "width": 30, "height": 24}],
        },
    )
    assert response.status_code == 200

    job_dir = output_dir / response.json()["job_id"]
    assert (job_dir / "snapshot.png").is_file()
    assert (job_dir / "crop_001.png").is_file()
    assert (job_dir / "boxes.json").is_file()

    with Image.open(job_dir / "crop_001.png") as crop:
        assert crop.size == (30, 24)

    metadata = json.loads((job_dir / "boxes.json").read_text(encoding="utf-8"))
    assert metadata["document"] == "drawing.pdf"
    assert metadata["boxes"] == [{"id": 1, "x": 10, "y": 12, "width": 30, "height": 24}]


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
            "action": "crop",
            "boxes": [{"id": 2, "x": 30, "y": 36, "width": 50, "height": 40}],
        },
    )
    saved = client.post(
        "/api/jobs",
        json={
            "document": "drawing.pdf",
            "page": 1,
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
    assert metadata["boxes"] == [{"id": 2, "x": 30, "y": 36, "width": 50, "height": 40}]


def test_crop_requires_a_box():
    client = TestClient(app_module.app)
    response = client.post(
        "/api/jobs",
        json={"document": "missing.pdf", "page": 1, "action": "crop", "boxes": []},
    )
    assert response.status_code == 400
