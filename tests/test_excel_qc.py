import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "excel-method" / "ocr_parser.py"
SPEC = importlib.util.spec_from_file_location("excel_ocr_parser_qc", MODULE_PATH)
OCR_PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCR_PARSER)
WRITER_SPEC = importlib.util.spec_from_file_location(
    "excel_writer_test",
    ROOT / "src" / "excel-method" / "excel_writer.py",
)
EXCEL_WRITER = importlib.util.module_from_spec(WRITER_SPEC)
WRITER_SPEC.loader.exec_module(EXCEL_WRITER)
PROFILE = OCR_PARSER.load_json(
    ROOT / "src" / "excel-method" / "tolerance_profile.json"
)


def qc_row(text, crop_number=1, abnormal=False):
    _, rows = OCR_PARSER.build_qc_rows(
        {
            "results": [
                {
                    "crop_number": crop_number,
                    "box": {
                        "page": 2,
                        "frame_location": "C4",
                    },
                    "ocr": text,
                    "abnormal": abnormal,
                }
            ]
        },
        job_dir=ROOT,
        tolerance_profile=PROFILE,
        unit="metric",
    )
    return rows[0]


def test_qc_gdt_uses_option_symbol_and_limit_tolerance():
    row = qc_row("[GD_POSITION] 0.02 A B C", crop_number=3)

    assert row["item"] == "2-3"
    assert row["zone"] == "C4"
    assert row["feature_lookup"] == "POSITION"
    assert row["specification"] == "0.02"
    assert row["tolerance_plus"] == "+0"
    assert row["tolerance_minus"] == "-0.02"
    assert row["measuring_equipment"] == "CMM"


def test_qc_feature_prefixes_are_removed_from_specification():
    cases = (
        ("4 X R0.20", "R", "", "4 X 0.20"),
        ("C0.5 X 45°", "C", "", "0.5 X 45°"),
        ("6 X ⌀0.3 THRU", "", "DIAMETER", "6 X 0.3 THRU"),
        ("45°", "", "LENGTH", "45"),
        ("DEPTH 10.00", "", "DEPTH", "10.00"),
    )

    for text, feature, lookup, specification in cases:
        row = qc_row(text)
        assert row["feature"] == feature
        assert row["feature_lookup"] == lookup
        assert row["specification"] == specification


def test_qc_unspecified_tolerance_uses_mip_profile():
    row = qc_row("40.00")

    assert row["tolerance_plus"] == "+0.05"
    assert row["tolerance_minus"] == "-0.05"


def test_angle_uses_profile_for_mip_and_qc():
    for text in ("45°", "4X 1 ±0.05 x 4 5°"):
        data = {
            "results": [
                {
                    "crop_number": 1,
                    "box": {"page": 1, "frame_location": "A1"},
                    "ocr": text,
                }
            ]
        }

        _, mip_rows = OCR_PARSER.build_mip_rows(data, ROOT, PROFILE, "metric")
        _, qc_rows = OCR_PARSER.build_qc_rows(data, ROOT, PROFILE, "metric")

        assert mip_rows[0]["excel_tolerance"] == "±0.5°"
        assert mip_rows[0]["control_tolerance"] == "±0.4°"
        assert qc_rows[0]["tolerance_plus"] == "+0.5°"
        assert qc_rows[0]["tolerance_minus"] == "-0.5°"


def test_explicit_angle_tolerance_still_takes_priority():
    row = qc_row("45° ±1°")

    assert row["tolerance_plus"] == "+1°"
    assert row["tolerance_minus"] == "-1°"


def test_abnormal_ocr_colors_only_the_excel_specification_red():
    row = qc_row(r"10_{\foo}", abnormal=True)

    class Worksheet:
        def __init__(self):
            self.cells = {}

        def Cells(self, excel_row, column):
            return self.cells.setdefault(
                (excel_row, column),
                SimpleNamespace(
                    Font=SimpleNamespace(Name=None, Color=None),
                    NumberFormat=None,
                    Value=None,
                ),
            )

    worksheet = Worksheet()
    layout = EXCEL_WRITER.TableLayout(
        sheet_name="TEST",
        data_start_row=1,
        template_data_rows=1,
        last_column=2,
        columns=(("specification", 1), ("tolerance_plus", 2)),
    )

    EXCEL_WRITER.write_rows(worksheet, [row], layout)

    assert row["abnormal"] is True
    assert worksheet.Cells(1, 1).Font.Color == 255
    assert worksheet.Cells(1, 2).Font.Color is None
