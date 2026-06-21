import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "src" / "excel-method" / "ocr_parser.py"
SPEC = importlib.util.spec_from_file_location("excel_ocr_parser_qc", MODULE_PATH)
OCR_PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCR_PARSER)
PROFILE = OCR_PARSER.load_json(
    ROOT / "src" / "excel-method" / "tolerance_profile.json"
)


def qc_row(text, crop_number=1):
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
