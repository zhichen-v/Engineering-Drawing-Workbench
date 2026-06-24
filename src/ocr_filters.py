from __future__ import annotations

import re

import numpy as np
import torch
from PIL import Image


NON_GD_LABELS = {"DIAMETER", "UNKNOWN"}
OCR_NUMBER_PATTERN = r"(?:\d+(?:\.\d+)?|\.\d+)"
OCR_TOLERANCE_PATTERN = rf"[+-]?{OCR_NUMBER_PATTERN}"


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


def crop_feature_control_region_candidates(
    image: Image.Image,
) -> list[tuple[Image.Image, Image.Image]]:
    grayscale = np.asarray(image.convert("L"))
    dark = grayscale < 190
    horizontal_lines = line_centers(dark.mean(axis=1) >= 0.5)

    top_line = bottom_line = None
    if len(horizontal_lines) >= 2:
        top_line, bottom_line = horizontal_lines[0], horizontal_lines[-1]
        frame = dark[top_line : bottom_line + 1]
        top_touch = frame[: min(3, frame.shape[0])].any(axis=0)
        bottom_touch = frame[-min(3, frame.shape[0]) :].any(axis=0)
        vertical_lines = line_centers((frame.mean(axis=0) >= 0.9) & top_touch & bottom_touch)
        edge_limit = max(6, round((bottom_line - top_line) * 0.3))
    elif horizontal_lines:
        edge_limit = max(6, round(image.height * 0.3))
        line = horizontal_lines[0]
        if line <= edge_limit:
            top_line = line
            frame = dark[top_line:]
        elif line >= image.height - 1 - edge_limit:
            bottom_line = line
            frame = dark[: bottom_line + 1]
        else:
            return []
        vertical_lines = line_centers(frame.mean(axis=0) >= 0.95)
    else:
        vertical_lines = line_centers(dark.mean(axis=0) >= 0.95)
        edge_limit = max(6, round(image.height * 0.3))

    inset = 2
    crop_top = top_line + inset if top_line is not None else 0
    crop_bottom = bottom_line - inset if bottom_line is not None else image.height
    if crop_bottom <= crop_top:
        return []
    minimum_cell_ink = max(3, round((crop_bottom - crop_top) * 0.2))
    candidates = []
    seen = set()

    def add_region(crop_left: int, right: int) -> None:
        crop_right = right - inset
        key = (crop_left, crop_right, right)
        if key in seen:
            return
        seen.add(key)
        if crop_right - crop_left <= inset * 2 or crop_bottom - crop_top <= inset * 2:
            return
        cell = dark[crop_top:crop_bottom, crop_left:crop_right]
        if int(cell.sum()) < minimum_cell_ink:
            return
        symbol = normalize_symbol_crop(
            image.crop((crop_left, crop_top, crop_right, crop_bottom))
        )
        if symbol is None:
            return

        value_right = vertical_lines[-1] - inset
        if value_right <= right + inset:
            value_right = image.width
        values = image.crop((right + inset, crop_top, value_right, crop_bottom))
        candidates.append((symbol, values))

    if len(vertical_lines) < 2:
        if len(vertical_lines) != 1 or top_line is None or bottom_line is None:
            return []
        right = vertical_lines[0]
        if right <= edge_limit:
            return []
        leading_region = dark[crop_top:crop_bottom, : max(0, right - inset)]
        value_region = dark[crop_top:crop_bottom, min(image.width, right + inset) :]
        if int(leading_region.sum()) < minimum_cell_ink or int(value_region.sum()) < minimum_cell_ink:
            return []
        add_region(0, right)
    else:
        first_vertical = vertical_lines[0]
        leading_region = dark[crop_top:crop_bottom, : max(0, first_vertical - inset)]
        leading_ink = int(leading_region.sum())
        has_leading_symbol = leading_ink >= minimum_cell_ink
        if first_vertical > edge_limit and has_leading_symbol:
            add_region(0, first_vertical)
        add_region(first_vertical + inset, vertical_lines[1])

    return candidates


def crop_feature_control_regions(
    image: Image.Image,
) -> tuple[Image.Image, Image.Image] | None:
    candidates = crop_feature_control_region_candidates(image)
    return candidates[0] if candidates else None


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
    best = None
    for symbol, values in crop_feature_control_region_candidates(image):
        label, confidence = classify_symbol(symbol, classifier, NON_GD_LABELS)
        if best is None or confidence > best[1]:
            best = (label, confidence, values)

    if best is None:
        return None

    label, confidence, values = best
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


def _is_unsigned_zero(value: str) -> bool:
    return re.fullmatch(r"(?:0+(?:\.0+)?|\.0+)", value) is not None


def _format_unilateral_tolerance(
    nominal: str,
    upper: str,
    lower: str,
) -> str | None:
    if _is_unsigned_zero(upper) and lower.startswith("-"):
        return f"{nominal}^{{{upper}}}_{{{lower}}}"
    if upper.startswith("+") and _is_unsigned_zero(lower):
        return f"{nominal}^{{{upper}}}_{{{lower}}}"
    return None


def _without_attached_zero(value: str) -> str | None:
    unsigned = value.lstrip("+-")
    if "." not in unsigned:
        return None
    _, fraction = unsigned.split(".", 1)
    if len(fraction) < 2 or not fraction.endswith("0"):
        return None
    return value[:-1]


def normalize_unilateral_tolerance(text: str) -> str:
    nominal = OCR_NUMBER_PATTERN
    tolerance = OCR_TOLERANCE_PATTERN
    detached_upper_sign = re.fullmatch(
        rf"(?P<nominal>{nominal})\s*\^\s*\{{\s*\+\s*\}}"
        rf"\s*(?P<upper>{nominal})\s+(?P<lower>{tolerance})",
        text,
    )
    if detached_upper_sign:
        normalized = _format_unilateral_tolerance(
            detached_upper_sign.group("nominal"),
            f"+{detached_upper_sign.group('upper')}",
            detached_upper_sign.group("lower"),
        )
        if normalized:
            return normalized

    pair_patterns = (
        rf"^(?P<nominal>{nominal})\s*\^\s*\{{\s*(?P<upper>{tolerance})\s*\}}"
        rf"\s*_\s*\{{\s*(?P<lower>{tolerance})\s*\}}$",
        rf"^(?P<nominal>{nominal})\s*_\s*\{{\s*(?P<lower>{tolerance})\s*\}}"
        rf"\s*\^\s*\{{\s*(?P<upper>{tolerance})\s*\}}$",
        rf"^(?P<nominal>{nominal})\s*(?P<upper>{tolerance})"
        rf"\s*_\s*\{{\s*(?P<lower>{tolerance})\s*\}}$",
        rf"^(?P<nominal>{nominal})\s*\^\s*\{{\s*(?P<upper>{tolerance})\s*\}}"
        rf"\s*(?P<lower>{tolerance})$",
        rf"^(?P<nominal>{nominal})\s+(?P<upper>{tolerance})"
        rf"\s+(?P<lower>{tolerance})$",
    )
    for pattern in pair_patterns:
        match = re.fullmatch(pattern, text)
        if match:
            normalized = _format_unilateral_tolerance(
                match.group("nominal"),
                match.group("upper"),
                match.group("lower"),
            )
            if normalized:
                return normalized

    upper_only = re.fullmatch(
        rf"(?P<nominal>{nominal})\s*\^\s*\{{\s*(?P<upper>{tolerance})\s*\}}",
        text,
    )
    if upper_only and upper_only.group("upper").startswith("+"):
        return (
            f"{upper_only.group('nominal')}^{{{upper_only.group('upper')}}}_{{0}}"
        )

    lower_only = re.fullmatch(
        rf"(?P<nominal>{nominal})\s*_\s*\{{\s*(?P<lower>{tolerance})\s*\}}",
        text,
    )
    if lower_only and lower_only.group("lower").startswith("-"):
        return (
            f"{lower_only.group('nominal')}^{{0}}_{{{lower_only.group('lower')}}}"
        )

    unmarked = re.fullmatch(
        rf"(?P<nominal>{nominal})\s*(?P<tolerance>[+-]{nominal})",
        text,
    )
    if not unmarked:
        return text

    nominal_value = unmarked.group("nominal")
    tolerance_value = unmarked.group("tolerance")
    if tolerance_value.startswith("-"):
        trimmed_nominal = _without_attached_zero(nominal_value)
        if trimmed_nominal:
            return f"{trimmed_nominal}^{{0}}_{{{tolerance_value}}}"

    trimmed_tolerance = _without_attached_zero(tolerance_value)
    if not trimmed_tolerance:
        return text
    if trimmed_tolerance.startswith("+"):
        return f"{nominal_value}^{{{trimmed_tolerance}}}_{{0}}"
    return f"{nominal_value}^{{0}}_{{{trimmed_tolerance}}}"


def flatten_unilateral_tolerance(text: str) -> str:
    match = re.fullmatch(
        rf"(?P<nominal>{OCR_NUMBER_PATTERN})"
        rf"\^\{{(?P<upper>{OCR_TOLERANCE_PATTERN})\}}"
        rf"_\{{(?P<lower>{OCR_TOLERANCE_PATTERN})\}}",
        text,
    )
    if not match:
        return text

    upper = match.group("upper")
    lower = match.group("lower")
    if not upper.startswith(("+", "-")):
        upper = f"+{upper}"
    if not lower.startswith(("+", "-")):
        lower = f"-{lower}"
    return f"{match.group('nominal')} {upper} {lower}"


def normalize_ocr_text(text: str) -> str:
    text = re.sub(
        r"(?:"
        r"\$\s*[\\/](?:varnothing|diameter|oslash|phi|bigcirc)\s*\$"
        r"|\{\s*[\\/](?:varnothing|diameter|oslash|phi|bigcirc)\s*\}"
        r"|[\\/](?:varnothing|diameter|oslash|phi|bigcirc)"
        r")",
        "⌀",
        text,
    )
    text = re.sub(
        r"(?:\^\s*\{\s*[\\/]circ\s*\}|\{\s*[\\/]circ\s*\}|[\\/]circ)",
        "°",
        text,
    )
    text = re.sub(r"\$?\s*\\pm\s*", "±", text)
    text = text.replace("$", "")
    text = re.sub(r"(\d)\.\s*(\d)\s+(\d)\b", r"\1.\2\3", text)
    text = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", text)
    text = " ".join(text.split())
    text = re.sub(r"([+-])\s+(?=\d|\.)", r"\1", text)
    text = normalize_unilateral_tolerance(text)
    return flatten_unilateral_tolerance(text)


def has_ocr_artifacts(text: str) -> bool:
    text = re.sub(r"\[GD_[A-Z_]+\]", "", text, flags=re.IGNORECASE)
    return re.search(r"[\\/{}_^]", text) is not None


def clean_gd_value_text(text: str) -> str:
    text = re.sub(r"\[\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\]", r"\1", text)
    text = re.sub(r"^(?:(?:\[[^\]]*\]|//+)\s*)+", "", text)
    return " ".join(text.replace("|", " ").split())
