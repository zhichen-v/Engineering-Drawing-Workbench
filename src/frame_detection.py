from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median

import fitz
import numpy as np
from PIL import Image, ImageDraw


DEFAULT_SCALE = 2.0
FRAME_DETECTION_DIR = "frame_detection"
ALPHA_LABELS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


@dataclass
class BorderLabel:
    label: str
    center: int
    bbox: list[int]
    sides: list[str]


@dataclass
class AxisCell:
    label: str
    center: int
    min: int
    max: int


@dataclass
class PageGrid:
    document: str
    page: int
    width: int
    height: int
    source: str
    frame_bbox: list[int] | None
    columns: list[AxisCell]
    rows: list[AxisCell]
    pdf_text_labels: list[BorderLabel]
    ocr_strip_files: dict[str, str]


def render_page_image(page: fitz.Page, scale: float) -> Image.Image:
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)


def normalize_label(text: str) -> str | None:
    text = text.strip().upper()
    if len(text) == 1 and text in ALPHA_LABELS:
        return text
    if text.isdigit() and 1 <= len(text) <= 2:
        return text
    return None


def label_kind(label: str) -> str:
    return "number" if label.isdigit() else "letter"


def word_rect_in_preview(page: fitz.Page, word: tuple, scale: float) -> fitz.Rect:
    rect = fitz.Rect(word[:4]) * page.rotation_matrix
    return fitz.Rect(
        rect.x0 * scale,
        rect.y0 * scale,
        rect.x1 * scale,
        rect.y1 * scale,
    )


def extract_pdf_border_candidates(
    page: fitz.Page,
    width: int,
    height: int,
    scale: float,
) -> list[dict]:
    band = max(48, int(min(width, height) * 0.028))
    candidates = []
    for word in page.get_text("words"):
        label = normalize_label(word[4])
        if label is None:
            continue

        rect = word_rect_in_preview(page, word, scale)
        cx = int(round((rect.x0 + rect.x1) / 2))
        cy = int(round((rect.y0 + rect.y1) / 2))
        sides = []
        if cy <= band:
            sides.append(("top", cy))
        if cy >= height - band:
            sides.append(("bottom", height - cy))
        if cx <= band:
            sides.append(("left", cx))
        if cx >= width - band:
            sides.append(("right", width - cx))
        for side, edge_distance in sides:
            candidates.append(
                {
                    "label": label,
                    "kind": label_kind(label),
                    "side": side,
                    "edge_distance": int(round(edge_distance)),
                    "center": [cx, cy],
                    "bbox": [
                        int(round(rect.x0)),
                        int(round(rect.y0)),
                        int(round(rect.x1)),
                        int(round(rect.y1)),
                    ],
                }
            )
    return candidates


def aggregate_axis_labels(
    candidates: list[dict],
    sides: tuple[str, str],
    coordinate_index: int,
) -> list[BorderLabel]:
    axis_candidates = [candidate for candidate in candidates if candidate["side"] in sides]
    by_kind = {"number": [], "letter": []}
    for candidate in axis_candidates:
        by_kind[candidate["kind"]].append(candidate)

    best_labels: list[BorderLabel] = []
    best_score = (-1, -1)
    for kind_candidates in by_kind.values():
        labels = labels_from_both_sides(kind_candidates, sides, coordinate_index)
        score = (sum(1 for label in labels if all(side in label.sides for side in sides)), len(labels))
        if score > best_score:
            best_score = score
            best_labels = labels

    if has_collapsed_centers(best_labels):
        return best_single_side_axis(axis_candidates, sides, coordinate_index)
    return best_labels


def labels_from_both_sides(
    candidates: list[dict],
    sides: tuple[str, str],
    coordinate_index: int,
) -> list[BorderLabel]:
    by_label = {}
    for candidate in candidates:
        by_label.setdefault(candidate["label"], []).append(candidate)

    labels = []
    for label, items in by_label.items():
        item_sides = sorted({item["side"] for item in items})
        coords = [item["center"][coordinate_index] for item in items]
        x0 = min(item["bbox"][0] for item in items)
        y0 = min(item["bbox"][1] for item in items)
        x1 = max(item["bbox"][2] for item in items)
        y1 = max(item["bbox"][3] for item in items)
        labels.append(
            BorderLabel(
                label=label,
                center=int(round(median(coords))),
                bbox=[x0, y0, x1, y1],
                sides=item_sides,
            )
        )

    two_sided = [label for label in labels if all(side in label.sides for side in sides)]
    if len(two_sided) >= 2:
        labels = two_sided
    return sorted(labels, key=lambda item: item.center)


def has_collapsed_centers(labels: list[BorderLabel]) -> bool:
    if len(labels) < 3:
        return False
    gaps = [
        right.center - left.center
        for left, right in zip(labels, labels[1:])
        if right.center > left.center
    ]
    if len(gaps) < 2:
        return False
    typical_gap = median(gaps)
    return min(gaps) < max(24, typical_gap * 0.35)


def best_single_side_axis(
    axis_candidates: list[dict],
    sides: tuple[str, str],
    coordinate_index: int,
) -> list[BorderLabel]:
    best_labels: list[BorderLabel] = []
    best_score = (-1, -1)
    for side in sides:
        for kind in ("number", "letter"):
            side_candidates = [
                candidate
                for candidate in axis_candidates
                if candidate["side"] == side and candidate["kind"] == kind
            ]
            labels = labels_from_one_side(side_candidates, coordinate_index)
            score = (sequence_score(labels), len(labels))
            if score > best_score:
                best_score = score
                best_labels = labels
    return best_labels


def labels_from_one_side(candidates: list[dict], coordinate_index: int) -> list[BorderLabel]:
    by_label = {}
    for candidate in candidates:
        current = by_label.get(candidate["label"])
        if current is None or candidate["edge_distance"] < current["edge_distance"]:
            by_label[candidate["label"]] = candidate

    labels = []
    for candidate in by_label.values():
        labels.append(
            BorderLabel(
                label=candidate["label"],
                center=candidate["center"][coordinate_index],
                bbox=candidate["bbox"],
                sides=[candidate["side"]],
            )
        )
    return sorted(labels, key=lambda item: item.center)


def sequence_score(labels: list[BorderLabel]) -> int:
    if len(labels) < 2:
        return 0
    values = [int(label.label) if label.label.isdigit() else ord(label.label) for label in labels]
    upward = sum(1 for left, right in zip(values, values[1:]) if right - left == 1)
    downward = sum(1 for left, right in zip(values, values[1:]) if right - left == -1)
    return max(upward, downward)


def infer_axis_cells(labels: list[BorderLabel], axis_size: int) -> list[AxisCell]:
    if len(labels) < 2:
        return []

    labels = sorted(labels, key=lambda item: item.center)
    centers = [label.center for label in labels]
    boundaries = [centers[0] - (centers[1] - centers[0]) / 2]
    boundaries.extend((left + right) / 2 for left, right in zip(centers, centers[1:]))
    boundaries.append(centers[-1] + (centers[-1] - centers[-2]) / 2)
    boundaries = [max(0, min(axis_size, int(round(value)))) for value in boundaries]

    return [
        AxisCell(
            label=label.label,
            center=label.center,
            min=boundaries[index],
            max=boundaries[index + 1],
        )
        for index, label in enumerate(labels)
    ]


def detect_image_frame_bbox(image: Image.Image) -> list[int] | None:
    gray = np.asarray(image.convert("L"))
    dark = gray < 225
    if not dark.any():
        return None

    height, width = dark.shape
    row_counts = dark.sum(axis=1)
    col_counts = dark.sum(axis=0)
    horizontal = np.where(row_counts > width * 0.35)[0]
    vertical = np.where(col_counts > height * 0.35)[0]
    if len(horizontal) and len(vertical):
        bbox = [int(vertical[0]), int(horizontal[0]), int(vertical[-1]), int(horizontal[-1])]
        if bbox[2] - bbox[0] > width * 0.5 and bbox[3] - bbox[1] > height * 0.5:
            return bbox

    ys, xs = np.where(dark)
    return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]


def grid_frame_bbox(columns: list[AxisCell], rows: list[AxisCell], fallback: list[int] | None) -> list[int] | None:
    if columns and rows:
        return [columns[0].min, rows[0].min, columns[-1].max, rows[-1].max]
    return fallback


def locate_point(grid: PageGrid, x: int, y: int) -> str | None:
    column = next((cell for cell in grid.columns if cell.min <= x <= cell.max), None)
    row = next((cell for cell in grid.rows if cell.min <= y <= cell.max), None)
    if column is None or row is None:
        return None
    if row.label.isalpha() and column.label.isdigit():
        return f"{row.label}{column.label}"
    if column.label.isalpha() and row.label.isdigit():
        return f"{column.label}{row.label}"
    return f"{row.label}{column.label}"


def locate_box(grid: PageGrid | None, box: dict) -> str | None:
    if grid is None:
        return None
    center_x = int(round(box["x"] + box["width"] / 2))
    center_y = int(round(box["y"] + box["height"] / 2))
    return locate_point(grid, center_x, center_y)


def save_ocr_strips(image: Image.Image, output_dir: Path, relative_root: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    width, height = image.size
    band = max(96, int(min(width, height) * 0.08))
    boxes = {
        "top": (0, 0, width, min(height, band)),
        "bottom": (0, max(0, height - band), width, height),
        "left": (0, 0, min(width, band), height),
        "right": (max(0, width - band), 0, width, height),
    }
    paths = {}
    for side, box in boxes.items():
        path = output_dir / f"{side}.png"
        image.crop(box).save(path)
        paths[side] = path.relative_to(relative_root).as_posix()
    return paths


def draw_overlay(image: Image.Image, grid: PageGrid, output_path: Path) -> None:
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    if grid.frame_bbox:
        draw.rectangle(grid.frame_bbox, outline=(220, 50, 50), width=4)
    for column in grid.columns:
        draw.line((column.min, 0, column.min, grid.height), fill=(50, 130, 220), width=2)
        draw.line((column.max, 0, column.max, grid.height), fill=(50, 130, 220), width=2)
        draw.text((column.center + 4, 24), column.label, fill=(20, 80, 180))
    for row in grid.rows:
        draw.line((0, row.min, grid.width, row.min), fill=(30, 150, 80), width=2)
        draw.line((0, row.max, grid.width, row.max), fill=(30, 150, 80), width=2)
        draw.text((24, row.center + 4), row.label, fill=(20, 120, 60))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    overlay.save(output_path)


def detect_page_grid(
    document: str,
    page_number: int,
    page: fitz.Page,
    image: Image.Image | None = None,
    scale: float = DEFAULT_SCALE,
    artifact_dir: Path | None = None,
    relative_root: Path | None = None,
) -> PageGrid:
    image = image.convert("RGB") if image is not None else render_page_image(page, scale)
    width, height = image.size
    candidates = extract_pdf_border_candidates(page, width, height, scale)
    column_labels = aggregate_axis_labels(candidates, ("top", "bottom"), 0)
    row_labels = aggregate_axis_labels(candidates, ("left", "right"), 1)
    columns = infer_axis_cells(column_labels, width)
    rows = infer_axis_cells(row_labels, height)
    image_frame = detect_image_frame_bbox(image)
    source = "pdf_text" if columns and rows else "image_frame_only"
    strips = {}
    if artifact_dir and relative_root:
        strips = save_ocr_strips(image, artifact_dir / "ocr_strips", relative_root)

    labels = sorted([*column_labels, *row_labels], key=lambda item: (item.center, item.label))
    grid = PageGrid(
        document=document,
        page=page_number,
        width=width,
        height=height,
        source=source,
        frame_bbox=grid_frame_bbox(columns, rows, image_frame),
        columns=columns,
        rows=rows,
        pdf_text_labels=labels,
        ocr_strip_files=strips,
    )
    if artifact_dir:
        draw_overlay(image, grid, artifact_dir / "overlay.png")
    return grid


def write_job_frame_detection(
    document: str,
    pdf_path: Path,
    pages: list[int],
    images: dict[int, Image.Image],
    job_dir: Path,
    scale: float = DEFAULT_SCALE,
) -> tuple[dict[int, PageGrid], Path]:
    frame_dir = job_dir / FRAME_DETECTION_DIR
    if frame_dir.exists():
        shutil.rmtree(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)

    grids = {}
    with fitz.open(pdf_path) as pdf:
        for page_number in pages:
            grid = detect_page_grid(
                document,
                page_number,
                pdf[page_number - 1],
                images.get(page_number),
                scale,
                artifact_dir=frame_dir / f"page_{page_number:03d}",
                relative_root=job_dir,
            )
            grids[page_number] = grid

    output_path = frame_dir / "frame_detection_results.json"
    output_path.write_text(
        json.dumps(
            {
                "document": document,
                "scale": scale,
                "pages": [asdict(grids[page_number]) for page_number in pages],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return grids, output_path


def run_probe(pdf_path: Path, output_dir: Path, scale: float, all_pages: bool) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    with fitz.open(pdf_path) as pdf:
        page_numbers = list(range(1, len(pdf) + 1)) if all_pages else [1]
        images = {
            page_number: render_page_image(pdf[page_number - 1], scale)
            for page_number in page_numbers
        }
    _, result_path = write_job_frame_detection(
        pdf_path.name,
        pdf_path,
        page_numbers,
        images,
        output_dir.parent if output_dir.name == FRAME_DETECTION_DIR else output_dir,
        scale,
    )
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect drawing frame labels and write debug artifacts.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--scale", type=float, default=DEFAULT_SCALE)
    parser.add_argument("--all-pages", action="store_true")
    args = parser.parse_args()

    result_path = run_probe(args.pdf.resolve(), args.output_dir.resolve(), args.scale, args.all_pages)
    print(f"Saved: {result_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
