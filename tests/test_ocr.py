import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from src import ocr, ocr_filters
from src.ocr import OCR_VERSION
from src.ocr_filters import clean_gd_value_text, crop_feature_control_regions


def test_crop_feature_control_regions_accepts_missing_top_frame():
    image = Image.new("RGB", (171, 43), "white")
    draw = ImageDraw.Draw(image)
    draw.line((11, 0, 11, 42), fill="black", width=1)
    draw.line((83, 0, 83, 42), fill="black", width=1)
    draw.line((164, 0, 164, 42), fill="black", width=1)
    draw.line((11, 42, 164, 42), fill="black", width=1)
    draw.polygon(((30, 28), (42, 10), (70, 10), (59, 28)), outline="black")

    regions = crop_feature_control_regions(image)

    assert regions is not None
    symbol, values = regions
    assert symbol.size == (128, 128)
    assert values.width > 0


def test_crop_feature_control_regions_removes_frame_at_image_edge():
    image = Image.new("RGB", (120, 48), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 2, 116, 45), outline="black")
    draw.line((58, 2, 58, 45), fill="black")
    draw.ellipse((17, 13, 41, 37), outline="black")
    draw.line((29, 8, 29, 42), fill="black")
    draw.line((12, 25, 46, 25), fill="black")

    regions = crop_feature_control_regions(image)

    assert regions is not None
    _, values = regions
    assert values.width > 0


def test_crop_feature_control_regions_accepts_leading_whitespace_before_frame():
    image = Image.new("RGB", (140, 56), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((22, 12, 132, 48), outline="black")
    draw.line((60, 12, 60, 48), fill="black")
    draw.line((96, 12, 96, 48), fill="black")
    draw.ellipse((32, 21, 50, 39), outline="black")
    draw.line((41, 18, 41, 42), fill="black")
    draw.line((29, 30, 53, 30), fill="black")

    regions = crop_feature_control_regions(image)

    assert regions is not None
    symbol, values = regions
    assert symbol.size == (128, 128)
    assert values.width > 0


def test_crop_feature_control_regions_accepts_cropped_outer_vertical_frame():
    image = Image.new("RGB", (138, 51), "white")
    draw = ImageDraw.Draw(image)
    draw.line((0, 3, 137, 3), fill="black")
    draw.line((0, 46, 137, 46), fill="black")
    draw.line((62, 3, 62, 46), fill="black")
    draw.polygon(((3, 34), (16, 12), (47, 12), (34, 34)), outline="black")
    draw.text((72, 8), "0.01", fill="black")

    regions = crop_feature_control_regions(image)

    assert regions is not None
    symbol, values = regions
    assert symbol.size == (128, 128)
    assert values.width > 0


def test_crop_feature_control_regions_rejects_text_without_horizontal_frame():
    image = Image.new("RGB", (191, 32), "white")
    draw = ImageDraw.Draw(image)
    draw.text((5, 2), "12.121+0.02", fill="black")

    assert crop_feature_control_regions(image) is None


def test_clean_gd_value_text_removes_visual_descriptions_and_numeric_frames():
    assert clean_gd_value_text("[圖形] 0.01") == "0.01"
    assert clean_gd_value_text("[0.01]") == "0.01"
    assert clean_gd_value_text("0.02 A B C") == "0.02 A B C"
    assert clean_gd_value_text("0.02 |A|B|C") == "0.02 A B C"


def test_has_diameter_symbol_stops_at_gap_before_text(monkeypatch):
    image = Image.new("RGB", (100, 40), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 8, 28, 32), outline="black")
    draw.line((5, 35, 29, 5), fill="black")
    draw.ellipse((37, 8, 49, 32), outline="black")
    classified_sizes = []

    monkeypatch.setattr(ocr_filters, "normalize_symbol_crop", lambda symbol: symbol)
    monkeypatch.setattr(
        ocr_filters,
        "classify_symbol",
        lambda symbol, _: classified_sizes.append(symbol.size) or ("DIAMETER", 1.0),
    )

    assert ocr_filters.has_diameter_symbol(image, {}, 0.99)
    assert classified_sizes == [(30, 40)]


def test_run_ocr_reuses_unchanged_box_results_before_loading_models(tmp_path, monkeypatch):
    box = {"id": 1, "page": 2, "x": 10, "y": 12, "width": 30, "height": 24}
    (tmp_path / "boxes.json").write_text(
        json.dumps({"job_id": "test-job", "boxes": [box]}),
        encoding="utf-8",
    )
    Image.new("RGB", (30, 24), "white").save(tmp_path / "crop_001.png")
    (tmp_path / "ocr_results.json").write_text(
        json.dumps(
            {
                "job_id": "test-job",
                "ocr_version": OCR_VERSION,
                "results": [{"crop_number": 1, "box": box, "ocr": "0.01"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        ocr,
        "load_symbol_classifier",
        lambda *_: (_ for _ in ()).throw(AssertionError("model should not load")),
    )
    output_path = ocr.run_ocr(
        SimpleNamespace(
            input_dir=tmp_path,
            classifier_checkpoint=Path("unused.pt"),
            classifier_threshold=0.4,
            diameter_threshold=0.99,
            device="auto",
            max_new_tokens=128,
            allow_model_download=False,
        )
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["results"] == [{"crop_number": 1, "box": box, "ocr": "0.01"}]


def test_run_ocr_only_recognizes_changed_boxes(tmp_path, monkeypatch):
    unchanged = {"id": 1, "page": 1, "x": 10, "y": 12, "width": 30, "height": 24}
    changed = {"id": 2, "page": 2, "x": 25, "y": 22, "width": 40, "height": 30}
    previous_changed = {**changed, "x": 20}
    (tmp_path / "boxes.json").write_text(
        json.dumps({"job_id": "test-job", "boxes": [unchanged, changed]}),
        encoding="utf-8",
    )
    Image.new("RGB", (30, 24), "white").save(tmp_path / "crop_001.png")
    Image.new("RGB", (40, 30), "white").save(tmp_path / "crop_002.png")
    (tmp_path / "ocr_results.json").write_text(
        json.dumps(
            {
                "job_id": "test-job",
                "ocr_version": OCR_VERSION,
                "results": [
                    {"crop_number": 1, "box": unchanged, "ocr": "KEEP"},
                    {"crop_number": 2, "box": previous_changed, "ocr": "OLD"},
                ],
            }
        ),
        encoding="utf-8",
    )

    recognized = []
    monkeypatch.setattr(ocr, "select_device", lambda *_: "cpu")
    monkeypatch.setattr(ocr, "load_symbol_classifier", lambda *_: {})
    monkeypatch.setattr(ocr, "load_base_model", lambda *_: (object(), object()))
    monkeypatch.setattr(ocr, "classify_gd_tag", lambda *_: None)
    monkeypatch.setattr(ocr, "has_diameter_symbol", lambda *_: False)
    monkeypatch.setattr(
        ocr,
        "recognize_image",
        lambda image, *_: recognized.append(image.size) or "UPDATED",
    )

    output_path = ocr.run_ocr(
        SimpleNamespace(
            input_dir=tmp_path,
            classifier_checkpoint=Path("unused.pt"),
            classifier_threshold=0.4,
            diameter_threshold=0.99,
            device="auto",
            max_new_tokens=128,
            allow_model_download=False,
        )
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert recognized == [(40, 30)]
    assert [item["ocr"] for item in result["results"]] == ["KEEP", "UPDATED"]


def test_run_ocr_reprocesses_results_from_an_older_version(tmp_path, monkeypatch):
    box = {"id": 1, "page": 1, "x": 10, "y": 12, "width": 30, "height": 24}
    (tmp_path / "boxes.json").write_text(
        json.dumps({"job_id": "test-job", "boxes": [box]}),
        encoding="utf-8",
    )
    Image.new("RGB", (30, 24), "white").save(tmp_path / "crop_001.png")
    (tmp_path / "ocr_results.json").write_text(
        json.dumps(
            {
                "job_id": "test-job",
                "ocr_version": OCR_VERSION - 1,
                "results": [{"crop_number": 1, "box": box, "ocr": "OLD"}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(ocr, "select_device", lambda *_: "cpu")
    monkeypatch.setattr(ocr, "load_symbol_classifier", lambda *_: {})
    monkeypatch.setattr(ocr, "load_base_model", lambda *_: (object(), object()))
    monkeypatch.setattr(ocr, "classify_gd_tag", lambda *_: None)
    monkeypatch.setattr(ocr, "has_diameter_symbol", lambda *_: False)
    monkeypatch.setattr(ocr, "recognize_image", lambda *_: "UPDATED")

    output_path = ocr.run_ocr(
        SimpleNamespace(
            input_dir=tmp_path,
            classifier_checkpoint=Path("unused.pt"),
            classifier_threshold=0.4,
            diameter_threshold=0.99,
            device="auto",
            max_new_tokens=128,
            allow_model_download=False,
        )
    )

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["ocr_version"] == OCR_VERSION
    assert result["results"][0]["ocr"] == "UPDATED"
