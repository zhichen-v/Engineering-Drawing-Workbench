import gc
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(frozen=True)
class TableLayout:
    sheet_name: str
    data_start_row: int
    template_data_rows: int
    last_column: int
    columns: tuple[tuple[str, int], ...]
    footer_start_row: int | None = None
    image_key: str | None = None
    image_column: int | None = None
    font_name: str = "Arial"
    font_columns: tuple[int, ...] | None = None


def fill_table_template(template_path, rows, output_path, layout):
    return fill_workbook_template(
        template_path,
        ((layout, rows),),
        output_path,
    )


def fill_workbook_template(template_path, tables, output_path):
    template_path = Path(template_path).resolve()
    output_path = Path(output_path).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, output_path)
    tables = tuple((layout, list(rows)) for layout, rows in tables)

    pythoncom, win32com = require_excel_com()
    pythoncom.CoInitialize()
    excel = None
    workbook = None
    worksheet = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.ScreenUpdating = False
        workbook = excel.Workbooks.Open(
            str(output_path),
            UpdateLinks=0,
            ReadOnly=False,
        )
        with tempfile.TemporaryDirectory(prefix="excel-images-") as image_dir:
            for layout, rows in tables:
                worksheet = workbook.Worksheets(layout.sheet_name)
                prepare_rows(worksheet, len(rows), layout)
                write_rows(worksheet, rows, layout)
                insert_images(
                    worksheet,
                    rows,
                    layout,
                    Path(image_dir),
                )
            workbook.Save()
    finally:
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
    return output_path


def prepare_rows(worksheet, row_count, layout):
    first_row = layout.data_start_row
    template_last_row = first_row + layout.template_data_rows - 1
    extra_rows = max(0, row_count - layout.template_data_rows)
    if extra_rows and layout.footer_start_row:
        footer_end_row = layout.footer_start_row + extra_rows - 1
        worksheet.Rows(
            f"{layout.footer_start_row}:{footer_end_row}"
        ).Insert()

    if row_count:
        last_target_row = first_row + row_count - 1
        if last_target_row != template_last_row:
            copy_row(
                worksheet,
                source_row=template_last_row,
                target_row=last_target_row,
                last_column=layout.last_column,
            )

    for offset in range(max(0, row_count - 1)):
        target_row = first_row + offset
        source_row = source_template_row(offset, row_count, layout)
        if target_row != source_row:
            copy_row(
                worksheet,
                source_row=source_row,
                target_row=target_row,
                last_column=layout.last_column,
            )

    for excel_row in range(first_row, first_row + row_count):
        worksheet.Range(
            worksheet.Cells(excel_row, 1),
            worksheet.Cells(excel_row, layout.last_column),
        ).ClearContents()
        worksheet.Rows(excel_row).Hidden = False

    for excel_row in range(first_row + row_count, template_last_row + 1):
        worksheet.Range(
            worksheet.Cells(excel_row, 1),
            worksheet.Cells(excel_row, layout.last_column),
        ).ClearContents()
        worksheet.Rows(excel_row).Hidden = True


def source_template_row(offset, total_rows, layout):
    first_row = layout.data_start_row
    last_row = first_row + layout.template_data_rows - 1
    if offset == 0:
        return first_row
    if offset == total_rows - 1:
        return last_row
    middle_rows = layout.template_data_rows - 2
    return first_row + 1 + ((offset - 1) % middle_rows)


def copy_row(worksheet, source_row, target_row, last_column):
    source = worksheet.Range(
        worksheet.Cells(source_row, 1),
        worksheet.Cells(source_row, last_column),
    )
    target = worksheet.Range(
        worksheet.Cells(target_row, 1),
        worksheet.Cells(target_row, last_column),
    )
    source.Copy(target)
    worksheet.Rows(target_row).RowHeight = worksheet.Rows(source_row).RowHeight


def write_rows(worksheet, rows, layout):
    font_columns = set(layout.font_columns or ())
    for offset, row in enumerate(rows):
        excel_row = layout.data_start_row + offset
        for key, column in layout.columns:
            cell = worksheet.Cells(excel_row, column)
            if not font_columns or column in font_columns:
                cell.Font.Name = layout.font_name
            cell.Value = row.get(key, "")


def insert_images(worksheet, rows, layout, image_dir):
    if not layout.image_key or not layout.image_column:
        return

    for offset, row in enumerate(rows):
        image_path = row.get(layout.image_key)
        if not image_path:
            continue

        source_path = Path(image_path)
        if not source_path.is_file():
            continue

        excel_row = layout.data_start_row + offset
        cell = worksheet.Cells(excel_row, layout.image_column)
        prepared_path = image_dir / f"row{excel_row:03d}.png"
        prepare_picture(source_path, prepared_path)
        shape = worksheet.Shapes.AddPicture(
            str(prepared_path),
            False,
            True,
            cell.Left,
            cell.Top,
            -1,
            -1,
        )
        shape.LockAspectRatio = True
        scale = min(
            (cell.Width * 0.9) / shape.Width,
            (cell.Height * 0.8) / shape.Height,
        )
        shape.Width *= scale
        shape.Height *= scale
        shape.Left = cell.Left + (cell.Width - shape.Width) / 2
        shape.Top = cell.Top + (cell.Height - shape.Height) / 2


def prepare_picture(source_path, output_path):
    image = Image.open(source_path).convert("RGB")
    trim_image_whitespace(image).save(output_path, "PNG")


def trim_image_whitespace(image):
    grayscale = image.convert("L")
    bounding_box = grayscale.point(
        lambda value: 0 if value >= 245 else 255
    ).getbbox()
    if not bounding_box:
        return image

    left, top, right, bottom = bounding_box
    return image.crop(
        (
            max(0, left - 2),
            max(0, top - 2),
            min(image.width, right + 2),
            min(image.height, bottom + 2),
        )
    )


def require_excel_com():
    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 and Microsoft Excel are required. Install pywin32 with: "
            "uv pip install --python .\\.venv\\Scripts\\python.exe pywin32"
        ) from exc
    return pythoncom, win32com
