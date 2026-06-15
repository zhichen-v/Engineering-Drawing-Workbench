from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor


ROOT = Path(__file__).resolve().parents[1]
SYMBOL_CLASSIFIER_DIR = Path(__file__).resolve().parent / "symbol-classifierdata"
CLASSIFIER_CHECKPOINT = SYMBOL_CLASSIFIER_DIR / "output" / "best.pt"
BASE_MODEL = "zai-org/GLM-OCR"
CROP_PATTERN = re.compile(r"crop_(\d+)\.png$")
NON_GD_LABELS = {"DIAMETER", "UNKNOWN"}

if str(SYMBOL_CLASSIFIER_DIR) not in sys.path:
    sys.path.insert(0, str(SYMBOL_CLASSIFIER_DIR))

from classifier_common import create_model, eval_transform


def select_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


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


def load_symbol_classifier(checkpoint_path: Path, device: torch.device) -> dict:
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=True)
    classes = checkpoint["classes"]
    model = create_model(checkpoint["model_name"], len(classes), pretrained=False).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return {
        "classes": classes,
        "device": device,
        "model": model,
        "transform": eval_transform(),
    }


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


def has_diameter_symbol(
    image: Image.Image,
    classifier: dict,
    threshold: float,
) -> bool:
    leading_width = min(image.width, image.height)
    symbol = normalize_symbol_crop(image.crop((0, 0, leading_width, image.height)))
    if symbol is None:
        return False

    label, confidence = classify_symbol(symbol, classifier)
    return label == "DIAMETER" and confidence >= threshold


def load_base_model(device: torch.device, allow_download: bool):
    local_files_only = not allow_download
    processor = AutoProcessor.from_pretrained(
        BASE_MODEL,
        local_files_only=local_files_only,
        trust_remote_code=True,
    )
    model_kwargs = {
        "local_files_only": local_files_only,
        "trust_remote_code": True,
    }
    if device.type == "cuda":
        model_kwargs.update(dtype=torch.float16, device_map={"": str(device)})

    model = AutoModelForImageTextToText.from_pretrained(BASE_MODEL, **model_kwargs)
    if device.type == "cpu":
        model = model.to(device)
    model.eval()
    return processor, model


def recognize_image(
    image: Image.Image,
    processor,
    model,
    max_new_tokens: int,
) -> str:
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": "Text Recognition:"},
            ],
        }
    ]
    inputs = processor.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=True,
        return_dict=True,
        return_tensors="pt",
    ).to(model.device)
    inputs.pop("token_type_ids", None)

    with torch.inference_mode():
        generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)
    return processor.decode(
        generated_ids[0][inputs["input_ids"].shape[1] :],
        skip_special_tokens=True,
    ).strip()


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


def load_box_metadata(input_dir: Path) -> tuple[str | None, dict[int, dict]]:
    metadata_path = input_dir / "boxes.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    boxes = {int(box["id"]): box for box in metadata["boxes"]}
    return metadata.get("job_id"), boxes


def crop_inputs(input_dir: Path) -> list[tuple[int, Path]]:
    crops = []
    for path in input_dir.glob("crop_*.png"):
        match = CROP_PATTERN.fullmatch(path.name)
        if match:
            crops.append((int(match.group(1)), path))
    return sorted(crops)


def resolve_test_input_dir(folder_name: str) -> Path:
    output_dir = (ROOT / "output").resolve()
    input_dir = (output_dir / folder_name).resolve()
    if input_dir.parent != output_dir:
        raise ValueError("--test must name one folder directly under output/")
    return input_dir


def run_ocr(args: argparse.Namespace) -> Path:
    input_dir = args.input_dir.resolve()
    crops = crop_inputs(input_dir)
    if not crops:
        raise FileNotFoundError(f"No crop_*.png files found in: {input_dir}")

    job_id, boxes = load_box_metadata(input_dir)
    missing_boxes = [number for number, _ in crops if number not in boxes]
    if missing_boxes:
        raise ValueError(f"Missing box metadata for crops: {missing_boxes}")

    output_path = input_dir / "ocr_results.json"
    previous_results = {}
    if output_path.is_file():
        previous_payload = json.loads(output_path.read_text(encoding="utf-8"))
        previous_results = {
            int(result["crop_number"]): result
            for result in previous_payload.get("results", [])
        }

    results_by_number = {}
    pending = []
    for crop_number, path in crops:
        previous = previous_results.get(crop_number)
        if previous and previous.get("box") == boxes[crop_number]:
            results_by_number[crop_number] = previous
        else:
            pending.append((crop_number, path))

    print(f"Reusing {len(results_by_number)} unchanged OCR result(s).")
    if pending:
        device = select_device(args.device)
        print(f"Using device: {device}")
        classifier = load_symbol_classifier(args.classifier_checkpoint.resolve(), device)
        print("Loading GLM-OCR from local cache..." if not args.allow_model_download else "Loading GLM-OCR...")
        processor, model = load_base_model(device, args.allow_model_download)

    for index, (crop_number, path) in enumerate(pending, start=1):
        print(f"[{index}/{len(pending)}] OCR: {path.name}")
        with Image.open(path) as opened:
            image = opened.convert("RGB")

        gd_result = classify_gd_tag(image, classifier, args.classifier_threshold)
        if gd_result:
            gd_tag, values = gd_result
            text = clean_gd_value_text(normalize_ocr_text(
                recognize_image(values, processor, model, args.max_new_tokens)
            ))
            text = f"{gd_tag} {text}".strip()
        else:
            text = normalize_ocr_text(
                recognize_image(image, processor, model, args.max_new_tokens)
            )
            if not text.startswith("⌀") and has_diameter_symbol(
                image,
                classifier,
                args.diameter_threshold,
            ):
                text = f"⌀ {text}".strip()

        results_by_number[crop_number] = {
            "crop_number": crop_number,
            "box": boxes[crop_number],
            "ocr": text,
        }

    results = [results_by_number[crop_number] for crop_number, _ in crops]
    output_path.write_text(
        json.dumps({"job_id": job_id, "results": results}, ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run GLM-OCR and GD symbol classification on crop images.")
    parser.add_argument(
        "--test",
        required=True,
        metavar="FOLDER_NAME",
        help="Read crop data from output/FOLDER_NAME and write ocr_results.json there.",
    )
    parser.add_argument("--classifier-checkpoint", type=Path, default=CLASSIFIER_CHECKPOINT)
    parser.add_argument("--classifier-threshold", type=float, default=0.4)
    parser.add_argument("--diameter-threshold", type=float, default=0.99)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument(
        "--allow-model-download",
        action="store_true",
        help="Allow downloading GLM-OCR when it is not available in the local Hugging Face cache.",
    )
    args = parser.parse_args()

    if not 0 <= args.classifier_threshold <= 1:
        parser.error("--classifier-threshold must be between 0 and 1.")
    if not 0 <= args.diameter_threshold <= 1:
        parser.error("--diameter-threshold must be between 0 and 1.")

    try:
        args.input_dir = resolve_test_input_dir(args.test)
    except ValueError as error:
        parser.error(str(error))

    output_path = run_ocr(args)
    print(f"Saved: {output_path}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
