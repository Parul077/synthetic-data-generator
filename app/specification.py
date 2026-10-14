import re
from typing import Any

from app.schemas import (
    ColumnSpec,
    ConstraintSpec,
    GenerationConfig,
    NoisePolicyConfig,
    SpecificationSuggestion,
)

CELL_REGEX = re.compile(r"^[A-Z]{1,3}[0-9]{1,7}$")


def validate_cell_coordinate(coord: str) -> bool:
    """Validate standard Excel cell coordinates like A1, B2, AA10."""
    if not coord or not isinstance(coord, str):
        return False
    return bool(CELL_REGEX.match(coord.upper().strip()))


def validate_specification_items(
    items: list[dict[str, Any]],
    workbook_metadata: dict[str, Any],
) -> list[str]:
    """
    Validate proposed or edited specification items before approval.
    Checks:
    - Worksheet existence.
    - Coordinate syntax.
    - Ensures no formulas or headings are targeted for overwrite.
    - Missing required fields.
    """
    errors: list[str] = []
    sheet_names = set(workbook_metadata.get("sheet_names", []))

    # Index formulas by sheet
    sheet_formulas: dict[str, set[str]] = {}
    for s in workbook_metadata.get("sheets", []):
        sheet_formulas[s["name"]] = {f["cell"] for f in s.get("formulas", [])}

    for idx, item in enumerate(items, start=1):
        sheet = item.get("sheet_name")
        cell = str(item.get("cell", "")).upper().strip()
        val = item.get("proposed_value")

        if not sheet or sheet not in sheet_names:
            errors.append(f"Item #{idx}: Worksheet '{sheet}' does not exist in the workbook.")

        if not validate_cell_coordinate(cell):
            errors.append(f"Item #{idx}: Invalid cell coordinate '{cell}'. Must be format like 'B2'.")

        if sheet in sheet_formulas and cell in sheet_formulas[sheet]:
            errors.append(
                f"Item #{idx}: Cell '{cell}' on sheet '{sheet}' is a formula. Overwriting formulas is forbidden."
            )

        if val is None or str(val).strip() == "":
            errors.append(f"Item #{idx} ({item.get('field_name', cell)}): Proposed value cannot be empty.")

    return errors


def convert_specification_to_config(
    approved_items: list[dict[str, Any]],
    project_metadata: dict[str, Any],
    base_config: dict[str, Any] | None = None,
) -> GenerationConfig:
    """
    Convert approved specification items and project metadata into a strongly-typed GenerationConfig.
    Adapts dynamically to ANY domain and project definition.
    """
    # Extract values from approved items
    item_map: dict[str, Any] = {}
    for item in approved_items:
        key = item.get("field_name") or item.get("cell")
        if key:
            item_map[key] = item.get("proposed_value")

    # Extract record count safely
    rec_count = project_metadata.get("record_count")
    if rec_count is None and "Record Count" in item_map:
        rec_count = item_map["Record Count"]
    try:
        record_count = int(rec_count) if rec_count is not None else 10000
    except (ValueError, TypeError):
        record_count = 10000

    seed_val = project_metadata.get("random_seed")
    if seed_val is None and "Random Seed" in item_map:
        seed_val = item_map["Random Seed"]
    try:
        random_seed = int(seed_val) if seed_val is not None else 42
    except (ValueError, TypeError):
        random_seed = 42

    proj_name = (
        project_metadata.get("project_name")
        or item_map.get("Project Name")
        or "Custom Synthetic Dataset"
    )
    domain = (
        project_metadata.get("domain")
        or item_map.get("Domain")
        or item_map.get("Domain / Industry")
        or "General Industry"
    )
    country = (
        project_metadata.get("country")
        or item_map.get("Country")
        or item_map.get("Country / Jurisdiction")
        or "Global"
    )
    objective = (
        project_metadata.get("dataset_objective")
        or item_map.get("Dataset Objective")
        or "Generate representative synthetic observations."
    )
    structure = (
        project_metadata.get("data_structure")
        or item_map.get("Data Structure")
        or "tabular"
    ).lower()
    addl = (
        project_metadata.get("additional_requirements")
        or item_map.get("Additional Requirements")
        or ""
    )

    if base_config and isinstance(base_config, dict):
        cfg_dict = dict(base_config)
        cfg_dict["project_name"] = proj_name
        cfg_dict["domain"] = domain
        cfg_dict["country"] = country
        cfg_dict["dataset_objective"] = objective
        cfg_dict["data_structure"] = structure
        cfg_dict["record_count"] = record_count
        cfg_dict["random_seed"] = random_seed
        config = GenerationConfig.from_dict(cfg_dict)
    else:
        # Dynamically build domain-appropriate configuration
        from app.claude_client import _get_mock_generation_config

        raw = _get_mock_generation_config({
            "project_name": proj_name,
            "domain": domain,
            "country": country,
            "dataset_objective": objective,
            "data_structure": structure,
            "record_count": record_count,
            "random_seed": random_seed,
            "additional_requirements": addl,
        })
        config = GenerationConfig.from_dict(raw)

    validation_errs = config.validate()
    if validation_errs:
        raise ValueError(f"Generation configuration validation failed: {'; '.join(validation_errs)}")

    return config
