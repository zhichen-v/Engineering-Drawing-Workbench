import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from excel_writer import fill_table_template
from ocr_parser import build_qc_rows, load_json
from sheet_layouts import QC_LAYOUT
from snapshot_excel import snapshot_workbook


def run(job_dir, template_path, tolerance_profile_path, output_dir, unit):
    job_dir = Path(job_dir).resolve()
    template_path = Path(template_path).resolve()
    tolerance_profile_path = Path(tolerance_profile_path).resolve()
    output_dir = Path(output_dir).resolve()

    ocr_path = job_dir / "ocr_results.json"
    if not ocr_path.is_file():
        raise FileNotFoundError(f"OCR result not found: {ocr_path}")
    if not template_path.is_file():
        raise FileNotFoundError(f"QC template not found: {template_path}")
    if not tolerance_profile_path.is_file():
        raise FileNotFoundError(
            f"Tolerance profile not found: {tolerance_profile_path}"
        )

    ocr_data = load_json(ocr_path)
    tolerance_profile = load_json(tolerance_profile_path)
    normalized_rows, output_rows = build_qc_rows(
        ocr_data,
        job_dir=job_dir,
        tolerance_profile=tolerance_profile,
        unit=unit,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    excel_path = output_dir / "QC_filled.xlsm"
    json_path = output_dir / "QC_fill_result.json"
    snapshot_path = output_dir / "QC_snapshot.png"

    fill_table_template(
        template_path,
        output_rows,
        excel_path,
        QC_LAYOUT,
    )
    snapshot = snapshot_workbook(
        excel_path,
        output_path=snapshot_path,
        sheet_name=QC_LAYOUT.sheet_name,
        min_rows=34,
        min_cols=QC_LAYOUT.last_column,
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
            "snapshot_output": str(snapshot_path),
            "snapshot_range": snapshot["range"],
            "excel_writer": "excel_com",
            "row_count": len(output_rows),
        },
        "normalized_rows": normalized_rows,
        "output_rows": output_rows,
    }
    json_path.write_text(
        json.dumps(debug, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return excel_path, json_path, snapshot_path, debug


def parse_args(argv=None):
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        description="Fill and snapshot the QC workbook from ocr_results.json."
    )
    parser.add_argument("--job", required=True, help="OCR job output folder.")
    parser.add_argument(
        "--template",
        default=str(repo_root / "template" / "QC.xlsm"),
    )
    parser.add_argument(
        "--tolerance-profile",
        default=str(Path(__file__).with_name("tolerance_profile.json")),
    )
    parser.add_argument(
        "--output-dir",
        help="Defaults to <job>/excel-output/QC.",
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
        else job_dir / "excel-output" / "QC"
    )
    excel_path, json_path, snapshot_path, debug = run(
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
                "snapshot": str(snapshot_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
