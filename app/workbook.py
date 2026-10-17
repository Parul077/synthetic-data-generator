import logging
from io import BytesIO
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import Cell, MergedCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation

logger = logging.getLogger("synthetic_data_generator.workbook")


def inspect_workbook(file_bytes: bytes) -> dict[str, Any]:
    """
    Inspect an XLSX workbook without saving or modifying it.

    Returns sheet metadata, dimensions, formulas, merged cells,
    validations, and populated-cell information.
    """
    if not file_bytes:
        raise ValueError("The uploaded workbook is empty.")

    workbook = load_workbook(
        BytesIO(file_bytes),
        read_only=False,
        data_only=False,
    )

    try:
        sheets = []

        for worksheet in workbook.worksheets:
            populated_cells = []
            formulas = []
            validation_details = []

            for row in worksheet.iter_rows():
                for cell in row:
                    if cell.value is not None:
                        populated_cells.append({
                            "cell": cell.coordinate,
                            "value": cell.value,
                            "data_type": cell.data_type,
                            "fill_type": cell.fill.fill_type if cell.fill else None,
                            "fill_color_type": (
                                cell.fill.fgColor.type
                                if cell.fill and cell.fill.fgColor
                                else None
                            ),
                            "fill_color": (
                                cell.fill.fgColor.rgb
                                if cell.fill and cell.fill.fgColor and cell.fill.fgColor.type == "rgb"
                                else None
                            ),
                            "has_comment": cell.comment is not None,
                        })

                    if cell.data_type == "f" or (isinstance(cell.value, str) and cell.value.startswith("=")):
                        formulas.append({
                            "cell": cell.coordinate,
                            "formula": cell.value,
                        })

            if hasattr(worksheet, "data_validations") and worksheet.data_validations:
                for validation in worksheet.data_validations.dataValidation:
                    validation_details.append({
                        "type": validation.type,
                        "formula1": validation.formula1,
                        "formula2": validation.formula2,
                        "operator": validation.operator,
                        "sqref": str(validation.sqref),
                    })

            sheets.append({
                "name": worksheet.title,
                "max_row": worksheet.max_row,
                "max_column": worksheet.max_column,
                "state": worksheet.sheet_state,
                "freeze_panes": (
                    str(worksheet.freeze_panes)
                    if worksheet.freeze_panes
                    else None
                ),
                "merged_cells": [
                    str(item)
                    for item in worksheet.merged_cells.ranges
                ],
                "populated_cells": populated_cells,
                "formulas": formulas,
                "data_validations": validation_details,
            })

        return {
            "sheet_names": workbook.sheetnames,
            "sheet_count": len(workbook.sheetnames),
            "sheets": sheets,
        }

    finally:
        workbook.close()


def _resolve_target_cell(ws: Any, cell_coord: str) -> Any:
    """
    Safely resolve the target cell for writing.
    If the specified coordinate points to a MergedCell (which openpyxl treats as read-only),
    resolve to the top-left root Cell of the containing merged range where values must be written.
    """
    clean_coord = str(cell_coord).upper().strip()
    try:
        cell = ws[clean_coord]
    except Exception as exc:
        logger.warning("Invalid cell coordinate '%s': %s", clean_coord, exc)
        return None

    if isinstance(cell, MergedCell) or type(cell).__name__ == "MergedCell":
        # Search merged cell ranges for the range containing this cell coordinate
        for rng in ws.merged_cells.ranges:
            if clean_coord in rng or (
                hasattr(cell, "row") and hasattr(cell, "column")
                and rng.min_row <= cell.row <= rng.max_row
                and rng.min_col <= cell.column <= rng.max_col
            ):
                root_cell = ws.cell(row=rng.min_row, column=rng.min_col)
                logger.info(
                    "Cell %s is a MergedCell in range %s. Writing to top-left root cell %s.",
                    clean_coord,
                    rng,
                    root_cell.coordinate,
                )
                return root_cell

    return cell


def apply_approved_specification(
    template_bytes: bytes,
    approved_items: list[dict[str, Any]],
) -> bytes:
    """
    Safely write approved specification values into a separate copy of the workbook.
    Never modifies the original workbook bytes.
    Protects formula cells, headings, and non-approved cells.
    Handles merged cells transparently by writing to the top-left root cell.
    """
    if not template_bytes:
        raise ValueError("Template workbook bytes cannot be empty.")

    output_stream = BytesIO()
    workbook = load_workbook(BytesIO(template_bytes), data_only=False)

    try:
        for item in approved_items:
            sheet_name = item.get("sheet_name")
            cell_coord = item.get("cell")
            val = item.get("proposed_value")

            if not sheet_name or not cell_coord:
                continue

            if sheet_name not in workbook.sheetnames:
                logger.warning("Sheet '%s' not found in workbook. Skipping.", sheet_name)
                continue

            ws = workbook[sheet_name]
            cell = _resolve_target_cell(ws, cell_coord)
            if cell is None:
                continue

            # Check if cell is an existing formula
            if getattr(cell, "data_type", None) == "f" or (
                isinstance(getattr(cell, "value", None), str)
                and str(cell.value).startswith("=")
            ):
                logger.warning(
                    "Skipping cell %s on sheet %s because it contains a formula (%s).",
                    cell_coord,
                    sheet_name,
                    getattr(cell, "value", None),
                )
                continue

            # Assign approved value safely
            try:
                cell.value = val
            except AttributeError as attr_err:
                # Defensive recovery in case openpyxl didn't resolve to root Cell
                logger.warning(
                    "Could not set value directly on cell %s (%s): %s. Attempting range search...",
                    cell_coord,
                    type(cell).__name__,
                    attr_err,
                )
                resolved = False
                for rng in ws.merged_cells.ranges:
                    if (
                        hasattr(cell, "row") and hasattr(cell, "column")
                        and rng.min_row <= cell.row <= rng.max_row
                        and rng.min_col <= cell.column <= rng.max_col
                    ):
                        root_cell = ws.cell(row=rng.min_row, column=rng.min_col)
                        root_cell.value = val
                        resolved = True
                        break
                if not resolved:
                    logger.warning("Failed to write to cell %s: %s", cell_coord, attr_err)

        workbook.save(output_stream)
        return output_stream.getvalue()

    finally:
        workbook.close()


def create_project_template_workbook(project_metadata: dict[str, Any] | None = None) -> bytes:
    """
    Dynamically create an Excel specification template customized for ANY user project definition,
    including Project_Overview, Data_Dictionary, and Business_Rules worksheets with styles, formulas,
    and input candidate cells.
    """
    from app.claude_client import _get_mock_generation_config

    meta = project_metadata or {}
    proj_name = meta.get("project_name") or "Synthetic Dataset"
    domain = meta.get("domain") or "General Industry"
    country = meta.get("country") or "Global"
    objective = meta.get("dataset_objective") or "Generate representative synthetic observations."
    structure = meta.get("data_structure") or "Tabular"
    rec_count = meta.get("record_count") if meta.get("record_count") is not None else 10000
    seed = meta.get("random_seed") if meta.get("random_seed") is not None else 42
    addl = meta.get("additional_requirements") or "Standard noise policy and business constraints."

    wb = Workbook()

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    title_font = Font(name="Calibri", size=13, bold=True, color="1F497D")
    section_font = Font(name="Calibri", size=11, bold=True, color="333333")
    regular_font = Font(name="Calibri", size=11)
    note_font = Font(name="Calibri", size=9, italic=True, color="555555")

    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    input_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    formula_fill = PatternFill(start_color="E2EFDA", end_color="E2EFDA", fill_type="solid")

    thin_border = Border(
        left=Side(style="thin", color="D9D9D9"),
        right=Side(style="thin", color="D9D9D9"),
        top=Side(style="thin", color="D9D9D9"),
        bottom=Side(style="thin", color="D9D9D9"),
    )

    # Sheet 1: Project_Overview
    ws_meta = wb.active
    ws_meta.title = "Project_Overview"
    ws_meta.views.sheetView[0].showGridLines = True

    ws_meta.merge_cells("A1:D1")
    ws_meta["A1"] = f"SYNTHETIC DATA SPECIFICATION: {proj_name}"
    ws_meta["A1"].font = title_font

    ws_meta["A2"] = "Complete the highlighted yellow input cells below before dataset generation."
    ws_meta["A2"].font = note_font

    meta_fields = [
        ("Project Name", "B4", proj_name),
        ("Domain / Industry", "B5", domain),
        ("Country / Jurisdiction", "B6", country),
        ("Record Count", "B7", rec_count),
        ("Data Structure", "B8", structure),
        ("Dataset Objective", "B9", objective),
        ("Random Seed", "B10", seed),
        ("Additional Requirements", "B11", addl),
    ]

    for label, cell_coord, _ in meta_fields:
        row_idx = int(cell_coord[1:])
        ws_meta[f"A{row_idx}"] = label
        ws_meta[f"A{row_idx}"].font = section_font
        ws_meta[f"A{row_idx}"].border = thin_border

        target_cell = ws_meta[cell_coord]
        target_cell.value = None  # Blank input candidate for specification builder
        target_cell.fill = input_fill
        target_cell.border = thin_border
        target_cell.font = regular_font

    ws_meta.column_dimensions["A"].width = 28
    ws_meta.column_dimensions["B"].width = 75

    # Sheet 2: Data_Dictionary
    ws_dict = wb.create_sheet(title="Data_Dictionary")
    ws_dict.views.sheetView[0].showGridLines = True

    dict_headers = [
        "Column Name", "Data Type", "Distribution", "Min / Categories", "Max / Proportions", "Derived Formula", "Noise Eligible"
    ]
    for col_idx, header in enumerate(dict_headers, start=1):
        cell = ws_dict.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Get domain-adapted column specs
    domain_cfg = _get_mock_generation_config(meta)
    columns_data = []
    for c in domain_cfg.get("columns", []):
        name = c.get("name", "")
        dtype = c.get("data_type", "float")
        dist = c.get("distribution", "normal")
        formula = c.get("formula", "")
        if formula and not str(formula).startswith("="):
            formula = f"={formula}"
        p = c.get("params", {})
        min_cats = ", ".join(p.get("categories", [])) if "categories" in p else str(c.get("hard_min", p.get("min", "")))
        max_props = ", ".join(f"{x:.1%}" for x in p.get("proportions", [])) if "proportions" in p else str(c.get("hard_max", p.get("max", "")))
        noise = "Yes" if c.get("noise_eligible", False) else "No"
        columns_data.append((name, dtype, dist, min_cats, max_props, formula, noise))

    for row_idx, row_data in enumerate(columns_data, start=2):
        for col_idx, val in enumerate(row_data, start=1):
            cell = ws_dict.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border
            if val and str(val).startswith("="):
                cell.fill = formula_fill

    for col_letter in ["A", "B", "C", "D", "E", "F", "G"]:
        ws_dict.column_dimensions[col_letter].width = 26

    # Sheet 3: Business_Rules
    ws_rules = wb.create_sheet(title="Business_Rules")
    ws_rules.views.sheetView[0].showGridLines = True

    rules_headers = ["Rule ID", "Rule Name", "Target Columns", "Logical Expression", "Criticality"]
    for col_idx, header in enumerate(rules_headers, start=1):
        cell = ws_rules.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border

    rules_data = []
    for r_idx, rule in enumerate(domain_cfg.get("constraints", []), start=1):
        r_id = f"RULE-{r_idx:02d}"
        r_name = rule.get("name", "Domain Constraint")
        r_cols = ", ".join(rule.get("columns", []))
        r_expr = rule.get("expression", "")
        r_crit = "CRITICAL"
        rules_data.append((r_id, r_name, r_cols, r_expr, r_crit))

    for row_idx, row_data in enumerate(rules_data, start=2):
        for col_idx, val in enumerate(row_data, start=1):
            cell = ws_rules.cell(row=row_idx, column=col_idx, value=val)
            cell.font = regular_font
            cell.border = thin_border

    for col_letter in ["A", "B", "C", "D", "E"]:
        ws_rules.column_dimensions[col_letter].width = 28

    # Add Data Validation dropdown to Data_Dictionary for Noise Eligible (Yes/No)
    dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=True)
    ws_dict.add_data_validation(dv)
    dv.add(f"G2:G{len(columns_data) + 1}")

    stream = BytesIO()
    wb.save(stream)
    wb.close()
    return stream.getvalue()


def create_sample_investment_workbook() -> bytes:
    """
    Backward-compatible generator for the Investment Customer / Client Data reference template.
    """
    return create_project_template_workbook({
        "project_name": "Investment Customer / Client Data",
        "domain": "Financial services",
        "country": "India",
        "dataset_objective": "Identify customers likely to increase their investments in equity or debt instruments.",
        "data_structure": "Tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "15% bounded perturbation on continuous features; accounting identities hold strictly.",
    })
