import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "src" / "excel-method" / "snapshot_excel.py"
SPEC = importlib.util.spec_from_file_location("snapshot_excel_test", MODULE_PATH)
snapshot_excel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot_excel)


def test_export_range_via_pdf_creates_png(tmp_path):
    output_path = tmp_path / "snapshot.png"

    class Worksheet:
        def ExportAsFixedFormat(self, Filename, **_kwargs):
            document = snapshot_excel.fitz.open()
            document.new_page(width=200, height=100)
            document.save(Filename)
            document.close()

    target = type("Target", (), {"Worksheet": Worksheet()})()
    snapshot_excel.export_range_via_pdf(target, output_path)

    assert output_path.is_file()
    with snapshot_excel.fitz.open(output_path) as image:
        assert image.page_count == 1
