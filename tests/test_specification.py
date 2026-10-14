import pytest

from app.schemas import ColumnSpec, GenerationConfig
from app.specification import (
    convert_specification_to_config,
    validate_cell_coordinate,
    validate_specification_items,
)


def test_validate_cell_coordinate():
    assert validate_cell_coordinate("A1") is True
    assert validate_cell_coordinate("B12") is True
    assert validate_cell_coordinate("AA100") is True
    assert validate_cell_coordinate("b2") is True  # Case insensitive
    assert validate_cell_coordinate("1A") is False
    assert validate_cell_coordinate("INVALID") is False
    assert validate_cell_coordinate("") is False
    assert validate_cell_coordinate(None) is False


def test_validate_specification_items_detects_errors():
    metadata = {
        "sheet_names": ["Specification"],
        "sheets": [
            {
                "name": "Specification",
                "formulas": [{"cell": "B3", "formula": "=B2*2"}],
            }
        ],
    }

    # 1. Invalid sheet
    items_bad_sheet = [{"sheet_name": "NonExistent", "cell": "B1", "proposed_value": "Test"}]
    errors = validate_specification_items(items_bad_sheet, metadata)
    assert any("does not exist" in e for e in errors)

    # 2. Invalid coordinate
    items_bad_coord = [{"sheet_name": "Specification", "cell": "99Z", "proposed_value": "Test"}]
    errors = validate_specification_items(items_bad_coord, metadata)
    assert any("Invalid cell coordinate" in e for e in errors)

    # 3. Overwriting formula
    items_formula = [{"sheet_name": "Specification", "cell": "B3", "proposed_value": "Test"}]
    errors = validate_specification_items(items_formula, metadata)
    assert any("Overwriting formulas is forbidden" in e for e in errors)

    # 4. Empty value
    items_empty = [{"sheet_name": "Specification", "cell": "B1", "proposed_value": ""}]
    errors = validate_specification_items(items_empty, metadata)
    assert any("cannot be empty" in e for e in errors)


def test_convert_specification_to_config_creates_valid_config():
    approved = [
        {"sheet_name": "Specification", "cell": "B1", "field_name": "Project Name", "proposed_value": "Custom Wealth Cohort"},
        {"sheet_name": "Specification", "cell": "B2", "field_name": "Record Count", "proposed_value": 5000},
    ]
    meta = {
        "project_name": "Custom Wealth Cohort",
        "domain": "Wealth Management",
        "country": "India",
        "record_count": 5000,
        "random_seed": 777,
    }

    config = convert_specification_to_config(approved, meta)
    assert isinstance(config, GenerationConfig)
    assert config.record_count == 5000
    assert config.random_seed == 777
    assert config.project_name == "Custom Wealth Cohort"
    assert len(config.columns) > 0


def test_convert_specification_for_agriculture_domain_has_no_financial_fields():
    meta = {
        "project_name": "Crop Yield Optimization",
        "domain": "Agriculture",
        "country": "Kenya",
        "dataset_objective": "Model soil nitrogen and rainfall impact on harvest crop yield",
        "record_count": 2000,
        "random_seed": 101,
    }

    config = convert_specification_to_config([], meta)
    assert config.domain == "Agriculture"
    col_names = [c.name for c in config.columns]

    # Must contain agronomic variables
    assert "soil_ph" in col_names
    assert "nitrogen_ppm" in col_names
    assert "total_nutrients_ppm" in col_names

    # Must NOT contain financial or banking variables
    assert "monthly_income" not in col_names
    assert "savings_balance" not in col_names
    assert "equity_allocation_pct" not in col_names


def test_convert_specification_for_healthcare_domain():
    meta = {
        "project_name": "Cardiovascular Patient Monitoring",
        "domain": "Healthcare",
        "country": "UK",
        "dataset_objective": "Track blood pressure and glucose outcomes",
        "record_count": 3000,
        "random_seed": 202,
    }

    config = convert_specification_to_config([], meta)
    assert config.domain == "Healthcare"
    col_names = [c.name for c in config.columns]

    assert "systolic_bp" in col_names
    assert "diastolic_bp" in col_names
    assert "pulse_pressure" in col_names
    assert "monthly_income" not in col_names


def test_convert_specification_for_retail_domain():
    meta = {
        "project_name": "E-Commerce Customer Retention",
        "domain": "Retail",
        "country": "US",
        "dataset_objective": "Evaluate customer churn and net annual spend",
        "record_count": 1500,
        "random_seed": 303,
    }

    config = convert_specification_to_config([], meta)
    assert config.domain == "Retail"
    col_names = [c.name for c in config.columns]

    assert "gross_annual_spend" in col_names
    assert "net_annual_spend" in col_names
    assert "churn_risk_target" in col_names
    assert "monthly_income" not in col_names


def test_generation_config_validation_rules():
    cols = [
        ColumnSpec(name="age", data_type="integer"),
        ColumnSpec(name="age", data_type="integer"),
    ]
    cfg = GenerationConfig(
        project_name="Test",
        domain="Finance",
        country="India",
        dataset_objective="Testing duplicate column validation",
        record_count=100,
        columns=cols,
    )
    errors = cfg.validate()
    assert any("Duplicate column names" in e for e in errors)


def test_convert_specification_for_custom_blank_project_uses_clean_defaults():
    meta = {
        "project_name": "",
        "domain": "",
        "country": "",
        "dataset_objective": "",
        "data_structure": "tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "",
    }
    config = convert_specification_to_config([], meta)
    assert isinstance(config, GenerationConfig)
    assert config.project_name == "Custom Synthetic Dataset"
    assert config.domain == "General Industry"
    assert config.country == "Global"
    assert config.record_count == 10000
    assert len(config.columns) > 0
    assert not config.validate()


def test_convert_specification_for_arbitrary_custom_domain():
    meta = {
        "project_name": "Wind Turbine Vibration & Power Output",
        "domain": "Renewable Energy",
        "country": "Denmark",
        "dataset_objective": "Model power generator vibration and gearbox wear",
        "record_count": 2500,
        "random_seed": 888,
    }
    config = convert_specification_to_config([], meta)
    assert config.domain == "Renewable Energy"
    assert config.project_name == "Wind Turbine Vibration & Power Output"
    col_names = [c.name for c in config.columns]

    # No domain contamination
    assert "savings_balance" not in col_names
    assert "monthly_income" not in col_names
    assert "systolic_bp" not in col_names
    assert "nitrogen_ppm" not in col_names
    assert "gross_annual_spend" not in col_names


def test_domain_presets_custom_blank_clears_defaults():
    from app.config import DOMAIN_PRESETS

    blank = DOMAIN_PRESETS["Custom / Blank Project"]
    assert blank["project_name"] == ""
    assert blank["domain"] == ""
    assert blank["country"] == ""
    assert blank["dataset_objective"] == ""
    assert blank["additional_requirements"] == ""

    # Presets have non-empty defaults
    for preset_name, preset in DOMAIN_PRESETS.items():
        if preset_name != "Custom / Blank Project":
            assert len(preset["project_name"]) > 0
            assert len(preset["domain"]) > 0
            assert len(preset["country"]) > 0
            assert len(preset["dataset_objective"]) > 0
