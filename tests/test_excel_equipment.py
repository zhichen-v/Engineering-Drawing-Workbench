import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "excel-method"
    / "ocr_parser.py"
)
SPEC = importlib.util.spec_from_file_location("excel_ocr_parser", MODULE_PATH)
OCR_PARSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OCR_PARSER)


@pytest.mark.parametrize(
    "text",
    (
        "4X R0.05",
        "C0.5 X 45°",
        "6X ⌀ 0.3 THRU",
        "Ø10.0",
        "DIA 8.5",
        "DIAMETER 12",
        "45°",
    ),
)
def test_profile_projector_dimensions(text):
    assert OCR_PARSER.resolve_equipment(text, "linear") == "Profile Projector"


def test_gdt_takes_priority_over_diameter():
    assert (
        OCR_PARSER.resolve_equipment(
            "[GD_POSITION] ⌀0.02 A B C",
            "gdt",
        )
        == "CMM"
    )


def test_surface_ra_is_not_treated_as_radius():
    assert (
        OCR_PARSER.resolve_equipment("Ra 0.8", "surface_roughness")
        == "Surface Roughness Tester"
    )


def test_datum_c_is_not_treated_as_chamfer():
    assert (
        OCR_PARSER.resolve_equipment("0.02 A B C", "linear")
        == "Digital Caliper"
    )
