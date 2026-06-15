from __future__ import annotations

import re

import numpy as np
import torch
from PIL import Image


NON_GD_LABELS = {"DIAMETER", "UNKNOWN"}


def line_centers(values: np.ndarray) -> list[int]:
    indices = np.flatnonzero(values)
    if not len(indices):
        return []

    centers = []
    start = previous = int(indices[0])
    for raw_index in indices[1:]:
        index = int(raw_index)
        if index > previous + 1:
            centers.append(round((start + previous) / 2))
            start = index
        previous = index
    centers.append(round((start + previous) / 2))
    return centers


def normalize_symbol_crop(symbol: Image.Image, size: int = 128) -> Image.Image | None:
    grayscale = np.asarray(symbol.convert("L"))
    dark_y, dark_x = np.where(grayscale < 190)
    if not len(dark_x):
        return None

    content = symbol.crop(
        (
            int(dark_x.min()),
            int(dark_y.min()),
            int(dark_x.max()) + 1,
            int(dark_y.max()) + 1,
        )
    ).convert("RGB")
    if content.width < 2 or content.height < 2:
        return None

    target = round(size * 0.7)
    scale = min(target / content.width, target / content.height)
    resized = content.resize(
        (max(1, round(content.width * scale)), max(1, round(content.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGB", (size, size), "white")
    canvas.paste(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return canvas


def crop_feature_control_regions(
    image: Image.Image,
) -> tuple[Image.Image, Image.Image] | None:
    grayscale = np.asarray(image.convert("L"))
    dark = grayscale < 190
    horizontal_lines = line_centers(dark.mean(axis=1) >= 0.5)
    if not horizontal_lines:
        return None

    top_line = bottom_line = None
    if len(horizontal_lines) >= 2:
        top_line, bottom_line = horizontal_lines[0], horizontal_lines[-1]
        frame = dark[top_line : bottom_line + 1]
        top_touch = frame[: min(3, frame.shape[0])].any(axis=0)
        bottom_touch = frame[-min(3, frame.shape[0]) :].any(axis=0)
        vertical_lines = line_centers((frame.mean(axis=0) >= 0.9) & top_touch & bottom_touch)
        edge_limit = max(6, round((bottom_line - top_line) * 0.3))
    else:
        vertical_lines = line_centers(dark.mean(axis=0) >= 0.7)
        edge_limit = max(6, round(image.height * 0.3))
        if horizontal_lines:
            line = horizontal_lines[0]
            if line <= edge_limit:
                top_line = line
            elif line >= image.height - 1 - edge_limit:
                bottom_line = line

    if len(vertical_lines) < 2:
        return None
    if vertical_lines[0] <= edge_limit:
        left, right = vertical_lines[0], vertical_lines[1]
        crop_left = left + 2
    else:
        left, right = 0, vertical_lines[0]
        crop_left = left

    inset = 2
    crop_right = right - inset
    crop_top = top_line + inset if top_line is not None else 0
    crop_bottom = bottom_line - inset if bottom_line is not None else image.height
    if crop_right - crop_left <= inset * 2 or crop_bottom - crop_top <= inset * 2:
        return None
    symbol = normalize_symbol_crop(
        image.crop((crop_left, crop_top, crop_right, crop_bottom))
    )
    if symbol is None:
        return None

    value_right = vertical_lines[-1] - inset
    if value_right <= right + inset:
        value_right = image.width
    values = image.crop((right + inset, crop_top, value_right, crop_bottom))
    return symbol, values


def classify_symbol(
    symbol: Image.Image,
    classifier: dict,
    excluded_labels: set[str] | None = None,
) -> tuple[str, float]:
    inputs = classifier["transform"](symbol).unsqueeze(0).to(classifier["device"])
    with torch.inference_mode():
        probabilities = torch.softmax(classifier["model"](inputs), dim=1)[0]

    probabilities = probabilities.clone()
    for label in excluded_labels or set():
        probabilities[classifier["classes"].index(label)] = -1
    confidence, index = torch.max(probabilities, dim=0)
    return classifier["classes"][int(index)], float(confidence)


def classify_gd_tag(
    image: Image.Image,
    classifier: dict,
    threshold: float,
) -> tuple[str, Image.Image] | None:
    regions = crop_feature_control_regions(image)
    if regions is None:
        return None
    symbol, values = regions

    label, confidence = classify_symbol(symbol, classifier, NON_GD_LABELS)
    if confidence < threshold:
        return None
    return f"[GD_{label}]", values


def crop_leading_symbol(image: Image.Image) -> Image.Image:
    dark_columns = (np.asarray(image.convert("L")) < 190).any(axis=0)
    ink_columns = np.flatnonzero(dark_columns)
    leading_width = min(image.width, image.height)
    if not len(ink_columns):
        return image.crop((0, 0, leading_width, image.height))

    first_ink = int(ink_columns[0])
    search_limit = min(image.width, first_ink + image.height)
    minimum_gap = max(2, round(image.height * 0.1))
    gap_start = None
    for column in range(first_ink, search_limit):
        if not dark_columns[column]:
            gap_start = column if gap_start is None else gap_start
        else:
            if gap_start is not None and column - gap_start >= minimum_gap:
                leading_width = gap_start
                break
            gap_start = None
    return image.crop((0, 0, leading_width, image.height))


def has_diameter_symbol(
    image: Image.Image,
    classifier: dict,
    threshold: float,
) -> bool:
    symbol = normalize_symbol_crop(crop_leading_symbol(image))
    if symbol is None:
        return False

    label, confidence = classify_symbol(symbol, classifier)
    return label == "DIAMETER" and confidence >= threshold


def normalize_ocr_text(text: str) -> str:
    text = re.sub(r"\$\s*\\(?:varnothing|diameter|oslash)\s*\$", "⌀", text)
    text = re.sub(r"\$?\s*\\pm\s*", "±", text)
    text = text.replace("$", "")
    text = re.sub(r"(\d)\.\s*(\d)\s+(\d)\b", r"\1.\2\3", text)
    return " ".join(text.split())


def clean_gd_value_text(text: str) -> str:
    text = re.sub(r"\[\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\]", r"\1", text)
    text = re.sub(r"^(?:(?:\[[^\]]*\]|//+)\s*)+", "", text)
    return " ".join(text.replace("|", " ").split())
