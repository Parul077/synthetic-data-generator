import pandas as pd
import pytest

from app.claude_client import _get_mock_generation_config
from app.generation import generate_synthetic_dataset
from app.schemas import GenerationConfig
from app.validation import repair_dataset, validate_dataset


@pytest.fixture
def clean_dataset_and_config() -> tuple[pd.DataFrame, GenerationConfig]:
    raw = _get_mock_generation_config({
        "project_name": "Investment Customer / Client Data",
        "record_count": 500,
        "random_seed": 42,
    })
    cfg = GenerationConfig.from_dict(raw)
    df = generate_synthetic_dataset(cfg)
    return df, cfg


def test_validation_clean_dataset_passes(clean_dataset_and_config):
    df, cfg = clean_dataset_and_config
    report = validate_dataset(df, cfg)
    assert report.failures == 0
    assert report.is_approved is True
    assert report.total_checks > 5
    assert all(item.status in ("PASS", "WARNING") for item in report.items)


def test_validation_detects_row_count_mismatch(clean_dataset_and_config):
    df, cfg = clean_dataset_and_config
    short_df = df.iloc[:200].copy()  # Configured for 500
    report = validate_dataset(short_df, cfg)
    assert report.failures >= 1
    row_check = next(i for i in report.items if i.check == "Row Count Verification")
    assert row_check.status == "FAIL"


def test_validation_detects_boundary_breach(clean_dataset_and_config):
    df, cfg = clean_dataset_and_config
    corrupted_df = df.copy()
    corrupted_df.loc[0, "age"] = 15  # Hard min is 21

    report = validate_dataset(corrupted_df, cfg)
    assert report.failures >= 1
    range_check = next(i for i in report.items if "Boundary" in i.check)
    assert range_check.status == "FAIL"


def test_validation_detects_invalid_category(clean_dataset_and_config):
    df, cfg = clean_dataset_and_config
    corrupted_df = df.copy()
    corrupted_df.loc[0, "gender"] = "Alien"

    report = validate_dataset(corrupted_df, cfg)
    assert report.failures >= 1
    cat_check = next(i for i in report.items if "Categorical Domain" in i.check)
    assert cat_check.status == "FAIL"


def test_repair_dataset_recovers_boundary_and_formula_breaches(clean_dataset_and_config):
    df, cfg = clean_dataset_and_config
    corrupted_df = df.copy()

    # Corrupt a derived column and an upper bound
    corrupted_df.loc[0, "total_financial_assets"] = -999999
    corrupted_df.loc[1, "age"] = 99  # Hard max is 72

    report_before = validate_dataset(corrupted_df, cfg)
    assert report_before.failures > 0

    repaired_df, report_after = repair_dataset(corrupted_df, cfg, report_before)
    assert repaired_df.loc[1, "age"] <= 72
    assert report_after.repair_attempted is True
    # The derived column was re-evaluated and passes
    assert report_after.failures == 0
