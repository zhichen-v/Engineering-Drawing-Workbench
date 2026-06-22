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
    text_columns: tuple[int, ...] = ()
    symbol_key: str | None = None
    symbol_column: int | None = None
    symbol_lookup_sheet: str | None = None
    symbol_lookup_key_column: int = 3
    symbol_lookup_value_column: int = 1


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
                clear_symbol_shapes(worksheet, len(rows), layout)
                write_rows(worksheet, rows, layout)
                insert_images(
                    worksheet,
                    rows,
                    layout,
                    Path(image_dir),
                )
                insert_symbols(workbook, worksheet, rows, layout)
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
    text_columns = set(layout.text_columns)
    for offset, row in enumerate(rows):
        excel_row = layout.data_start_row + offset
        for key, column in layout.columns:
            cell = worksheet.Cells(excel_row, column)
            if not font_columns or column in font_columns:
                cell.Font.Name = layout.font_name
            if column in text_columns:
                cell.NumberFormat = "@"
            cell.Value = row.get(key, "")
            if row.get("abnormal") and key in ("excel_specification", "specification"):
                cell.Font.Color = 255


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


def clear_symbol_shapes(worksheet, row_count, layout):
    if not layout.symbol_column:
        return

    first_row = layout.data_start_row
    last_row = first_row + max(row_count, layout.template_data_rows) - 1
    for index in range(worksheet.Shapes.Count, 0, -1):
        shape = worksheet.Shapes(index)
        if (
            shape.TopLeftCell.Column == layout.symbol_column
            and first_row <= shape.TopLeftCell.Row <= last_row
        ):
            shape.Delete()


def insert_symbols(workbook, worksheet, rows, layout):
    if not (
        layout.symbol_key
        and layout.symbol_column
        and layout.symbol_lookup_sheet
    ):
        return

    source_sheet = workbook.Worksheets(layout.symbol_lookup_sheet)
    lookup = {}
    used = source_sheet.UsedRange
    last_row = used.Row + used.Rows.Count - 1
    for row_number in range(used.Row, last_row + 1):
        value = source_sheet.Cells(
            row_number,
            layout.symbol_lookup_key_column,
        ).Value
        if value:
            lookup[normalize_symbol_key(value)] = row_number

    for offset, row in enumerate(rows):
        key = row.get(layout.symbol_key)
        if not key:
            continue

        source_row = lookup.get(normalize_symbol_key(key))
        if not source_row:
            continue

        target = worksheet.Cells(
            layout.data_start_row + offset,
            layout.symbol_column,
        )
        source = source_sheet.Cells(
            source_row,
            layout.symbol_lookup_value_column,
        )
        if source.Value not in (None, ""):
            source.Copy()
            target.PasteSpecial(Paste=-4122)
            target.Value = source.Value
            continue

        source_shape = find_cell_shape(source_sheet, source)
        if source_shape is None:
            continue
        source_shape.Copy()
        worksheet.Activate()
        worksheet.Paste()
        fit_shape_to_cell(
            worksheet.Shapes(worksheet.Shapes.Count),
            target,
        )


def normalize_symbol_key(value):
    return " ".join(
        str(value).replace("_", " ").replace("-", " ").upper().split()
    )


def find_cell_shape(worksheet, cell):
    center_y = cell.Top + cell.Height / 2
    candidates = []
    for shape in worksheet.Shapes:
        if shape.Width <= 0 or shape.Height <= 0:
            continue
        overlaps_column = (
            shape.Left < cell.Left + cell.Width
            and shape.Left + shape.Width > cell.Left
        )
        if not overlaps_column:
            continue
        distance = abs(shape.Top + shape.Height / 2 - center_y)
        candidates.append((distance, shape))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def fit_shape_to_cell(shape, cell):
    shape.LockAspectRatio = True
    scale = min(
        (cell.Width * 0.75) / shape.Width,
        (cell.Height * 0.75) / shape.Height,
    )
    shape.Width *= scale
    shape.Height *= scale
    shape.Left = cell.Left + (cell.Width - shape.Width) / 2
    shape.Top = cell.Top + (cell.Height - shape.Height) / 2
    shape.Placement = 1


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
