from pathlib import Path

import fitz

from src import frame_detection


ROOT = Path(__file__).resolve().parents[1]


def test_pdf_text_grid_detection_maps_points_to_frame_locations():
    with fitz.open(ROOT / "test-ED" / "59102-0SBG000.pdf") as pdf:
        grid = frame_detection.detect_page_grid(
            "59102-0SBG000.pdf",
            1,
            pdf[0],
            scale=frame_detection.DEFAULT_SCALE,
        )

    assert grid.source == "pdf_text"
    assert [column.label for column in grid.columns] == ["8", "7", "6", "5", "4", "3", "2", "1"]
    assert [row.label for row in grid.rows] == ["F", "E", "D", "C", "B", "A"]

    column = next(cell for cell in grid.columns if cell.label == "3")
    row = next(cell for cell in grid.rows if cell.label == "D")

    assert frame_detection.locate_point(grid, column.center, row.center) == "D3"


def test_box_location_uses_center_point():
    grid = frame_detection.PageGrid(
        document="drawing.pdf",
        page=1,
        width=20,
        height=20,
        source="test",
        frame_bbox=[0, 0, 20, 20],
        columns=[
            frame_detection.AxisCell(label="1", center=5, min=0, max=10),
            frame_detection.AxisCell(label="2", center=15, min=11, max=20),
        ],
        rows=[
            frame_detection.AxisCell(label="A", center=5, min=0, max=10),
            frame_detection.AxisCell(label="B", center=15, min=11, max=20),
        ],
        pdf_text_labels=[],
        ocr_strip_files={},
    )

    box = {"x": 9, "y": 9, "width": 20, "height": 20}

    assert frame_detection.locate_box(grid, box) == "B2"


def test_image_frame_fallback_keeps_probe_useful_without_pdf_text_labels():
    with fitz.open(ROOT / "test-ED" / "sample_14.pdf") as pdf:
        grid = frame_detection.detect_page_grid(
            "sample_14.pdf",
            1,
            pdf[0],
            scale=frame_detection.DEFAULT_SCALE,
        )

    assert grid.source == "image_frame_only"
    assert grid.frame_bbox is not None
    assert grid.columns == []
    assert grid.rows == []
