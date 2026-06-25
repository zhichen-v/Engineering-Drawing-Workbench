from pathlib import Path

import fitz

from src import frame_detection


def create_test_pdf(path, frame_grid):
    pdf = fitz.open()
    page = pdf.new_page(width=400, height=300)
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


def test_pdf_text_grid_detection_maps_points_to_frame_locations(tmp_path):
    pdf_path = tmp_path / "grid.pdf"
    create_test_pdf(pdf_path, frame_grid=True)

    with fitz.open(pdf_path) as pdf:
        grid = frame_detection.detect_page_grid(
            pdf_path.name,
            1,
            pdf[0],
            scale=frame_detection.DEFAULT_SCALE,
        )

    assert grid.source == "pdf_text"
    assert [column.label for column in grid.columns] == ["1", "2", "3", "4"]
    assert [row.label for row in grid.rows] == ["A", "B", "C", "D"]

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


def test_axis_labels_keep_complete_single_side_sequence():
    candidates = []
    for label, x in zip(("6", "5", "4", "3", "2", "1"), (300, 840, 1400, 1960, 2520, 3060)):
        candidates.append(
            {
                "label": label,
                "kind": "number",
                "side": "top",
                "edge_distance": 20,
                "center": [x, 20],
                "bbox": [x - 10, 0, x + 10, 40],
            }
        )
    for label, x in zip(("6", "5", "4", "3", "2"), (300, 840, 1400, 1960, 2520)):
        candidates.append(
            {
                "label": label,
                "kind": "number",
                "side": "bottom",
                "edge_distance": 20,
                "center": [x, 2300],
                "bbox": [x - 10, 2280, x + 10, 2320],
            }
        )

    labels = frame_detection.aggregate_axis_labels(candidates, ("top", "bottom"), 0)

    assert [label.label for label in labels] == ["6", "5", "4", "3", "2", "1"]


def test_image_frame_fallback_keeps_probe_useful_without_pdf_text_labels(tmp_path):
    pdf_path = tmp_path / "frame.pdf"
    create_test_pdf(pdf_path, frame_grid=False)

    with fitz.open(pdf_path) as pdf:
        grid = frame_detection.detect_page_grid(
            pdf_path.name,
            1,
            pdf[0],
            scale=frame_detection.DEFAULT_SCALE,
        )

    assert grid.source == "image_frame_only"
    assert grid.frame_bbox is not None
    assert grid.columns == []
    assert grid.rows == []
