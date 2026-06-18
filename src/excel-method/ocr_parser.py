import json
import re
from decimal import Decimal
from pathlib import Path


NUMBER_PATTERN = r"(?:\d+(?:\.\d+)?|\.\d+)"
GD_TAG_PATTERN = re.compile(r"\[GD[_-][^\]]+\]", re.IGNORECASE)
SURFACE_PATTERN = re.compile(
    r"(?:\bRA\b|\bRMS\b|SURFACE\s+(?:FINISH|ROUGHNESS)|[µμ]m)",
    re.IGNORECASE,
)
MULTIPLICITY_PATTERN = re.compile(r"^\s*\d+\s*[Xx]\s*")
PROFILE_PROJECTOR_PATTERN = re.compile(
    rf"(?:"
    rf"(?<![A-Z])R\s*{NUMBER_PATTERN}"
    rf"|(?<![A-Z])C\s*{NUMBER_PATTERN}"
    rf"|[⌀Ø∅Φφ]"
    rf"|\bDIA(?:METER)?\b"
    rf")",
    re.IGNORECASE,
)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_mip_rows(ocr_data, job_dir, tolerance_profile, unit):
    normalized_rows = [
        parse_ocr_result(result, job_dir, tolerance_profile, unit)
        for result in ocr_data.get("results", [])
    ]
    return normalized_rows, [row["output_row"] for row in normalized_rows]


def parse_ocr_result(result, job_dir, tolerance_profile, unit):
    raw_text = normalize_text(result.get("ocr", ""))
    crop_number = int(result["crop_number"])
    box = result.get("box") or {}
    page = box.get("page", result.get("page", ""))
    zone = result.get("frame_location") or box.get("frame_location", "")

    is_gdt = GD_TAG_PATTERN.search(raw_text) is not None
    is_surface = SURFACE_PATTERN.search(raw_text) is not None
    warnings = []

    if is_gdt:
        kind = "gdt"
        specification = "\u200b"
        tolerance_value = first_dimension_number(
            GD_TAG_PATTERN.sub("", raw_text).lstrip(" >")
        )
        tolerance = f"≤{tolerance_value}" if tolerance_value else "-"
        tolerance_source = "gdt_limit"
        image_path = Path(job_dir) / f"crop_{crop_number:03d}.png"
        if not image_path.is_file():
            warnings.append(f"Missing crop image: {image_path}")
            image_path = None
    elif is_surface:
        kind = "surface_roughness"
        specification = raw_text
        tolerance_value = surface_value(raw_text)
        tolerance = f"≤{tolerance_value}" if tolerance_value else "-"
        tolerance_source = "surface_limit"
        image_path = None
    else:
        kind = "linear"
        specification, explicit_tolerance = split_linear_tolerance(raw_text)
        nominal_token = first_dimension_number(specification)
        if explicit_tolerance:
            tolerance = explicit_tolerance
            tolerance_source = "explicit_ocr"
        else:
            tolerance = tolerance_from_profile(
                nominal_token,
                tolerance_profile=tolerance_profile,
                unit=unit,
            )
            tolerance_source = (
                "tolerance_profile" if tolerance != "-" else "unresolved"
            )
        image_path = None
        if looks_like_untagged_gdt(raw_text):
            warnings.append(
                "OCR resembles an untagged GD&T frame; kept as text because no [GD_*] tag was present."
            )

    equipment = resolve_equipment(raw_text, kind)
    output_row = {
        "item": crop_number,
        "drawing_sheet": page,
        "zone": zone,
        "excel_specification": specification,
        "excel_tolerance": tolerance,
        "control_tolerance": scale_tolerance(tolerance, Decimal("0.8")),
        "measuring_equipment": equipment,
        "production_section": "MCM",
        "suqc": "*",
        "ipqc": "○",
        "ogqc": "◎",
    }
    if image_path:
        output_row["specification_image"] = str(image_path)

    return {
        "source": result,
        "parsed": {
            "kind": kind,
            "normalized_ocr": raw_text,
            "specification": specification,
            "tolerance": tolerance,
            "tolerance_source": tolerance_source,
            "unit_profile": unit,
            "specification_image": str(image_path) if image_path else None,
        },
        "equipment": {
            "equipment": equipment,
            "rule": equipment_rule(raw_text, kind),
        },
        "warnings": warnings,
        "output_row": output_row,
    }


def normalize_text(text):
    value = "" if text is None else str(text).strip()
    replacements = {
        "\u7c23": "±",
        "¡Ó": "±",
        "+/-": "±",
        "ø": "⌀",
        "∅": "⌀",
        "Ø": "⌀",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return re.sub(r"\s+", " ", value).strip()


def split_linear_tolerance(text):
    bilateral = re.search(rf"±\s*(?P<value>{NUMBER_PATTERN})", text)
    if bilateral:
        value = bilateral.group("value")
        specification = clean_specification(
            f"{text[:bilateral.start()]} {text[bilateral.end():]}"
        )
        return specification, f"±{value}"

    paired = re.search(
        rf"(?P<first_sign>[+-])\s*(?P<first>{NUMBER_PATTERN})"
        rf"\s*/?\s*(?P<second_sign>[+-])\s*(?P<second>{NUMBER_PATTERN})",
        text,
    )
    if paired:
        plus = "0"
        minus = "0"
        for sign_group, value_group in (
            ("first_sign", "first"),
            ("second_sign", "second"),
        ):
            if paired.group(sign_group) == "+":
                plus = paired.group(value_group)
            else:
                minus = paired.group(value_group)
        specification = clean_specification(
            f"{text[:paired.start()]} {text[paired.end():]}"
        )
        return specification, f"+{plus}/-{minus}"

    single_sided = re.search(
        rf"\s(?P<sign>[+-])\s*(?P<value>{NUMBER_PATTERN})\s*$",
        text,
    )
    if single_sided:
        value = single_sided.group("value")
        if single_sided.group("sign") == "+":
            tolerance = f"+{value}/-0"
        else:
            tolerance = f"+0/-{value}"
        return clean_specification(text[: single_sided.start()]), tolerance

    return clean_specification(text), ""


def clean_specification(text):
    value = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,;)])", r"\1", value)


def first_dimension_number(text):
    value = MULTIPLICITY_PATTERN.sub("", text)
    match = re.search(NUMBER_PATTERN, value)
    return match.group(0) if match else ""


def surface_value(text):
    ra_match = re.search(
        rf"\bRA\b\s*(?P<value>{NUMBER_PATTERN})",
        text,
        re.IGNORECASE,
    )
    if ra_match:
        return ra_match.group("value")

    unit_match = re.search(
        rf"(?P<value>{NUMBER_PATTERN})\s*[µμ]m",
        text,
        re.IGNORECASE,
    )
    if unit_match:
        return unit_match.group("value")

    values = re.findall(NUMBER_PATTERN, text)
    return values[-1] if values else ""


def tolerance_from_profile(nominal_token, tolerance_profile, unit):
    if not nominal_token:
        return "-"

    unit_profile = (tolerance_profile.get("unit_tables") or {}).get(unit) or {}
    table = (unit_profile.get("tables") or {}).get("linear_decimal") or {}
    decimal_places = (
        len(nominal_token.split(".", 1)[1]) if "." in nominal_token else 0
    )
    row = table.get(str(decimal_places))
    if not row:
        return "-"

    plus = str(row.get("plus", ""))
    minus = str(row.get("minus", plus))
    if not plus or not minus:
        return "-"
    if plus == minus:
        return f"±{plus}"
    return f"+{plus}/-{minus}"


def scale_tolerance(tolerance, factor):
    if not tolerance or tolerance == "-":
        return ""

    def scale_number(match):
        value = Decimal(match.group(0)) * factor
        return format(value.normalize(), "f")

    return re.sub(NUMBER_PATTERN, scale_number, tolerance)


def looks_like_untagged_gdt(text):
    return re.fullmatch(
        rf">?\s*{NUMBER_PATTERN}(?:\s+[A-Z](?:\([A-Z]\))?)+",
        text,
        re.IGNORECASE,
    ) is not None


def resolve_equipment(raw_text, kind):
    combined = raw_text.upper()

    if kind == "gdt":
        return "CMM"
    if kind == "surface_roughness":
        return "Surface Roughness Tester"
    if PROFILE_PROJECTOR_PATTERN.search(combined):
        return "Profile Projector"

    direct_map = {
        "CMM": "CMM",
        "CALIPER": "Digital Caliper",
        "PROFILE PROJECTOR": "Profile Projector",
        "PLUG GAUGE": "Thread Plug Gauge",
        "THREAD GAUGE": "Thread Plug Gauge",
        "ROUGHNESS TESTER": "Surface Roughness Tester",
        "VISUAL": "Visual",
    }
    for token, equipment in direct_map.items():
        if token in combined:
            return equipment

    if re.search(r"\b(?:UNC|UNF|UNEF|NPT|BSP|THREAD|TAP|TAPPED)\b", combined):
        return "Thread Plug Gauge"
    if any(
        token in combined
        for token in (
            "CHIP",
            "CHIPOUT",
            "SCRATCH",
            "DIRT",
            "DENT",
            "BURR",
            "RUST",
            "APPEARANCE",
            "COSMETIC",
        )
    ):
        return "Visual"
    return "Digital Caliper"


def equipment_rule(raw_text, kind):
    equipment = resolve_equipment(raw_text, kind)
    rules = {
        "CMM": "GD&T control.",
        "Profile Projector": "Radius, chamfer, or diameter dimension.",
        "Surface Roughness Tester": "Surface roughness requirement.",
        "Thread Plug Gauge": "Thread or tapped-hole callout.",
        "Visual": "Appearance or workmanship requirement.",
        "Digital Caliper": "Default dimensional measurement.",
    }
    return rules[equipment]
