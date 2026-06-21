from excel_writer import TableLayout


MIP_LAYOUT = TableLayout(
    sheet_name="MIP",
    data_start_row=14,
    template_data_rows=13,
    last_column=19,
    columns=(
        ("item", 1),
        ("drawing_sheet", 2),
        ("zone", 3),
        ("excel_specification", 4),
        ("excel_tolerance", 5),
        ("suqc", 6),
        ("ipqc", 7),
        ("ogqc", 8),
        ("measuring_equipment", 9),
        ("production_section", 10),
    ),
    image_key="specification_image",
    image_column=4,
    font_name="Arial",
    font_columns=(1, 2, 3, 4, 5, 9, 10),
)


SUQC_LAYOUT = TableLayout(
    sheet_name="SUQC",
    data_start_row=15,
    template_data_rows=12,
    footer_start_row=27,
    last_column=19,
    columns=(
        ("item", 1),
        ("drawing_sheet", 2),
        ("zone", 3),
        ("excel_specification", 4),
        ("excel_tolerance", 5),
        ("suqc", 6),
        ("control_tolerance", 7),
        ("measuring_equipment", 9),
        ("production_section", 10),
    ),
    image_key="specification_image",
    image_column=4,
    font_name="Arial",
    font_columns=(1, 2, 3, 4, 5, 7, 9, 10),
)


IPQC_LAYOUT = TableLayout(
    sheet_name="IPQC",
    data_start_row=15,
    template_data_rows=12,
    footer_start_row=27,
    last_column=19,
    columns=(
        ("item", 1),
        ("drawing_sheet", 2),
        ("zone", 3),
        ("excel_specification", 4),
        ("excel_tolerance", 5),
        ("ipqc", 6),
        ("control_tolerance", 7),
        ("measuring_equipment", 9),
        ("production_section", 10),
    ),
    image_key="specification_image",
    image_column=4,
    font_name="Arial",
    font_columns=(1, 2, 3, 4, 5, 7, 9, 10),
)


OGQC_LAYOUT = TableLayout(
    sheet_name="OGQC",
    data_start_row=15,
    template_data_rows=13,
    footer_start_row=28,
    last_column=21,
    columns=(
        ("item", 1),
        ("drawing_sheet", 2),
        ("zone", 3),
        ("excel_specification", 4),
        ("excel_tolerance", 5),
        ("ogqc", 6),
        ("measuring_equipment", 7),
    ),
    image_key="specification_image",
    image_column=4,
    font_name="Arial",
    font_columns=(1, 2, 3, 4, 5, 7),
)


FILL_LAYOUTS = (
    MIP_LAYOUT,
    SUQC_LAYOUT,
    IPQC_LAYOUT,
    OGQC_LAYOUT,
)


QC_LAYOUT = TableLayout(
    sheet_name="OGQC",
    data_start_row=8,
    template_data_rows=20,
    footer_start_row=28,
    last_column=17,
    columns=(
        ("item", 1),
        ("zone", 2),
        ("feature", 3),
        ("specification", 4),
        ("tolerance_plus", 5),
        ("tolerance_minus", 6),
        ("measuring_equipment", 7),
    ),
    font_name="Arial",
    font_columns=(1, 2, 3, 4, 5, 6, 7),
    text_columns=(1, 2, 3, 4, 5, 6, 7),
    symbol_key="feature_lookup",
    symbol_column=3,
    symbol_lookup_sheet="選項",
)
