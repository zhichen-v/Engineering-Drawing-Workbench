import argparse
import gc
import sys
import tempfile
from pathlib import Path

import fitz


DEFAULT_SHEET = "MIP"


def snapshot_workbook(
    workbook_path,
    output_path=None,
    sheet_name=DEFAULT_SHEET,
    cell_range=None,
    min_rows=26,
    min_cols=19,
    visible=False,
):
    workbook_path = Path(workbook_path).resolve()
    if not workbook_path.is_file():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    pythoncom, win32com = require_excel_com()
    output_path = (
        Path(output_path).resolve()
        if output_path
        else default_output_path(workbook_path, sheet_name)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pythoncom.CoInitialize()
    excel = None
    workbook = None
    worksheet = None
    target = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = bool(visible)
        excel.DisplayAlerts = False
        excel.ScreenUpdating = True

        workbook = excel.Workbooks.Open(
            str(workbook_path),
            UpdateLinks=0,
            ReadOnly=True,
        )
        worksheet = workbook.Worksheets(sheet_name)
        target = (
            worksheet.Range(cell_range)
            if cell_range
            else auto_range(worksheet, min_rows, min_cols)
        )

        worksheet.Activate()
        target.Select()
        export_range_via_pdf(target, output_path)
        address = str(target.Address).replace("$", "")
        return {
            "workbook": str(workbook_path),
            "sheet": sheet_name,
            "range": address,
            "output": str(output_path),
        }
    finally:
        target = None
        worksheet = None
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        if excel is not None:
            excel.CutCopyMode = False
            excel.Quit()
        workbook = None
        excel = None
        gc.collect()
        pythoncom.CoUninitialize()


def auto_range(worksheet, min_rows, min_cols):
    used = worksheet.UsedRange
    last_row = max(used.Row + used.Rows.Count - 1, min_rows)
    last_col = max(used.Column + used.Columns.Count - 1, min_cols)
    return worksheet.Range(
        worksheet.Cells(1, 1),
        worksheet.Cells(last_row, last_col),
    )


def export_range_via_pdf(target, output_path):
    worksheet = target.Worksheet

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
        pdf_path = Path(temporary.name)
    try:
        worksheet.ExportAsFixedFormat(
            Type=0,
            Filename=str(pdf_path),
            Quality=0,
            IncludeDocProperties=True,
            IgnorePrintAreas=False,
            OpenAfterPublish=False,
        )
        with fitz.open(pdf_path) as pdf:
            pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).save(output_path)
    finally:
        pdf_path.unlink(missing_ok=True)


def default_output_path(workbook_path, sheet_name):
    safe_sheet = "".join(
        char if char.isalnum() else "_" for char in sheet_name
    ).strip("_")
    return workbook_path.with_name(f"{safe_sheet}_snapshot.png")


def require_excel_com():
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 and Microsoft Excel are required for snapshots. "
            "Install pywin32 with: "
            "uv pip install --python .\\.venv\\Scripts\\python.exe pywin32"
        ) from exc
    return pythoncom, win32com


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Create a PNG snapshot from an Excel worksheet range."
    )
    parser.add_argument("workbook", help="Path to .xls or .xlsx workbook.")
    parser.add_argument("--sheet", default=DEFAULT_SHEET)
    parser.add_argument(
        "--range",
        dest="cell_range",
        help="Excel range to capture, e.g. A1:S33.",
    )
    parser.add_argument("--output", help="Output PNG path.")
    parser.add_argument("--min-rows", type=int, default=26)
    parser.add_argument("--min-cols", type=int, default=19)
    parser.add_argument("--visible", action="store_true")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    result = snapshot_workbook(
        args.workbook,
        output_path=args.output,
        sheet_name=args.sheet,
        cell_range=args.cell_range,
        min_rows=args.min_rows,
        min_cols=args.min_cols,
        visible=args.visible,
    )
    print(f"snapshot: {result['output']}")
    print(f"sheet: {result['sheet']}")
    print(f"range: {result['range']}")


if __name__ == "__main__":
    main()
