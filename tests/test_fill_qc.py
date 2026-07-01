import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
METHOD_DIR = ROOT / "src" / "excel-method"
sys.path.insert(0, str(METHOD_DIR))
SPEC = importlib.util.spec_from_file_location("fill_qc_test", METHOD_DIR / "fill_QC.py")
FILL_QC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILL_QC)


def workbook_sheet_names(path):
    namespace = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(path) as workbook:
        root = ET.fromstring(workbook.read("xl/workbook.xml"))
    return [sheet.attrib["name"] for sheet in root.find("m:sheets", namespace)]


def test_fb_qc_template_includes_symbol_lookup_sheet():
    assert workbook_sheet_names(ROOT / "template" / "FB_QC.XLSM") == [
        "OGQC",
        "選項",
    ]


def test_fb_qc_run_uses_variant_layout_and_output_names(tmp_path, monkeypatch):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "ocr_results.json").write_text("{}", encoding="utf-8")
    template_path = tmp_path / "FB_QC.XLSM"
    template_path.write_bytes(b"template")
    profile_path = tmp_path / "tolerance.json"
    profile_path.write_text("{}", encoding="utf-8")
    captured = {}

    monkeypatch.setattr(FILL_QC, "load_json", lambda path: {})
    monkeypatch.setattr(FILL_QC, "build_qc_rows", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(
        FILL_QC,
        "fill_table_template",
        lambda template, rows, output, layout: captured.update(layout=layout),
    )
    monkeypatch.setattr(
        FILL_QC,
        "snapshot_workbook",
        lambda *args, **kwargs: captured.update(snapshot=kwargs)
        or {"range": "A1:Q35"},
    )

    excel_path, json_path, snapshot_path, _ = FILL_QC.run(
        job_dir,
        template_path,
        profile_path,
        tmp_path / "excel-output" / "FB_QC",
        "metric",
        output_format="FB_QC",
    )

    assert excel_path.name == "FB_QC_filled.xlsm"
    assert json_path.name == "FB_QC_fill_result.json"
    assert snapshot_path.name == "FB_QC_snapshot.png"
    assert captured["layout"].template_data_rows == 11
    assert captured["layout"].footer_start_row == 19
    assert captured["layout"].symbol_lookup_sheet == "選項"
    assert captured["snapshot"]["min_rows"] == 35
