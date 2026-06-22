import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from excel_writer import fill_workbook_template
from ocr_parser import build_mip_rows, load_json
from sheet_layouts import FILL_LAYOUTS
from snapshot_excel import snapshot_workbook_sheets


IGNORED_SHEETS = ("檢驗表修改紀錄",)


def run(job_dir, template_path, tolerance_profile_path, output_dir, unit):
    job_dir = Path(job_dir).resolve()
    template_path = Path(template_path).resolve()
    tolerance_profile_path = Path(tolerance_profile_path).resolve()
    output_dir = Path(output_dir).resolve()

    ocr_path = job_dir / "ocr_results.json"
    if not ocr_path.is_file():
        raise FileNotFoundError(f"OCR result not found: {ocr_path}")
    if not template_path.is_file():
        raise FileNotFoundError(f"MIP template not found: {template_path}")
    if not tolerance_profile_path.is_file():
        raise FileNotFoundError(
            f"Tolerance profile not found: {tolerance_profile_path}"
        )

    ocr_data = load_json(ocr_path)
    tolerance_profile = load_json(tolerance_profile_path)
    normalized_rows, output_rows = build_mip_rows(
        ocr_data,
        job_dir=job_dir,
        tolerance_profile=tolerance_profile,
        unit=unit,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / "MIP_filled.xls"
    json_path = output_dir / "MIP_fill_result.json"

    fill_workbook_template(
        template_path,
        ((layout, output_rows) for layout in FILL_LAYOUTS),
        excel_path,
    )

    snapshots = snapshot_workbook_sheets(
        excel_path,
        (
            {
                "sheet_name": layout.sheet_name,
                "output_path": output_dir / f"{layout.sheet_name}_snapshot.png",
                "min_rows": layout.data_start_row + len(output_rows) + 4,
                "min_cols": layout.last_column,
            }
            for layout in FILL_LAYOUTS
        ),
    )

    debug = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "job_id": ocr_data.get("job_id", job_dir.name),
            "ocr_path": str(ocr_path),
            "template_path": str(template_path),
            "tolerance_profile_path": str(tolerance_profile_path),
            "unit_profile": unit,
            "excel_output": str(excel_path),
            "snapshot_outputs": {
                sheet: snapshot["output"]
                for sheet, snapshot in snapshots.items()
            },
            "snapshot_ranges": {
                sheet: snapshot["range"]
                for sheet, snapshot in snapshots.items()
            },
            "excel_writer": "excel_com",
            "row_count": len(output_rows),
            "filled_sheets": [
                layout.sheet_name for layout in FILL_LAYOUTS
            ],
            "ignored_sheets": list(IGNORED_SHEETS),
            "control_item_policy": {
                "SUQC": "tolerance multiplied by 0.8",
                "IPQC": "tolerance multiplied by 0.8",
            },
        },
        "normalized_rows": normalized_rows,
        "output_rows": output_rows,
    }
    json_path.write_text(
        json.dumps(debug, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return excel_path, json_path, snapshots, debug


def parse_args(argv=None):
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Fill and snapshot all inspection sheets from OCR data."
    )
    parser.add_argument("--job", required=True, help="OCR job output folder.")
    parser.add_argument(
        "--template",
        default=str(repo_root / "template" / "MIP.xls"),
    )
    parser.add_argument(
        "--tolerance-profile",
        default=str(Path(__file__).with_name("tolerance_profile.json")),
    )
    parser.add_argument(
        "--output-dir",
        help="Defaults to <job>/excel-output/MIP.",
    )
    parser.add_argument(
        "--unit",
        choices=("metric", "inch"),
        default="metric",
        help="Tolerance profile unit table used for unspecified tolerances.",
    )
    return parser.parse_args(argv)


def configure_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def main(argv=None):
    configure_stdout()
    args = parse_args(argv)
    job_dir = Path(args.job)
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else job_dir / "excel-output" / "MIP"
    )
    excel_path, json_path, snapshots, debug = run(
        job_dir=job_dir,
        template_path=args.template,
        tolerance_profile_path=args.tolerance_profile,
        output_dir=output_dir,
        unit=args.unit,
    )
    print(
        json.dumps(
            {
                "status": "success",
                "rows": debug["metadata"]["row_count"],
                "excel": str(excel_path),
                "json": str(json_path),
                "snapshots": {
                    sheet: result["output"]
                    for sheet, result in snapshots.items()
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
