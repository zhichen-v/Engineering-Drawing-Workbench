from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor


ROOT = Path(__file__).resolve().parents[1]
SYMBOL_CLASSIFIER_DIR = Path(__file__).resolve().parent / "symbol-classifierdata"
CLASSIFIER_CHECKPOINT = SYMBOL_CLASSIFIER_DIR / "output" / "best.pt"
BASE_MODEL = "zai-org/GLM-OCR"
CROP_PATTERN = re.compile(r"crop_(\d+)\.png$")
OCR_VERSION = 3

if str(SYMBOL_CLASSIFIER_DIR) not in sys.path:
    sys.path.insert(0, str(SYMBOL_CLASSIFIER_DIR))

from classifier_common import create_model, eval_transform

try:
    from .ocr_filters import (
        clean_gd_value_text,
        classify_gd_tag,
        classify_symbol,
        crop_feature_control_regions,
        crop_leading_symbol,
        has_diameter_symbol,
        line_centers,
        normalize_ocr_text,
        normalize_symbol_crop,
    )
except ImportError:
    from ocr_filters import (
        clean_gd_value_text,
        classify_gd_tag,
        classify_symbol,
        crop_feature_control_regions,
        crop_leading_symbol,
        has_diameter_symbol,
        line_centers,
        normalize_ocr_text,
        normalize_symbol_crop,
    )


def select_device(requested: str) -> torch.device:
    if requested != "auto":
        return torch.device(requested)
    return torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


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
        if previous_payload.get("ocr_version") == OCR_VERSION:
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
        json.dumps(
            {"job_id": job_id, "ocr_version": OCR_VERSION, "results": results},
            ensure_ascii=False,
            indent=2,
        )
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
