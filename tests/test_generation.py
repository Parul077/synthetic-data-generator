import numpy as np
import pandas as pd
import pytest

from app.claude_client import _get_mock_generation_config
from app.generation import (
    evaluate_formula,
    generate_reproducible_script,
    generate_synthetic_dataset,
)
from app.schemas import GenerationConfig


@pytest.fixture
def base_config() -> GenerationConfig:
    raw = _get_mock_generation_config({
        "project_name": "Investment Customer / Client Data",
        "domain": "Financial services",
        "record_count": 1000,
        "random_seed": 42,
    })
    return GenerationConfig.from_dict(raw)


def test_generation_exact_row_and_column_counts(base_config):
    df = generate_synthetic_dataset(base_config)
    assert len(df) == 1000
    assert len(df.columns) == len(base_config.columns)
    assert list(df.columns) == [c.name for c in base_config.columns]


def test_generation_deterministic_reproducibility(base_config):
    df1 = generate_synthetic_dataset(base_config)
    df2 = generate_synthetic_dataset(base_config)
    pd.testing.assert_frame_equal(df1, df2)


def test_generation_different_seeds_produce_different_data(base_config):
    cfg1 = base_config
    cfg2 = GenerationConfig.from_dict(base_config.to_dict())
    cfg2.random_seed = 9999

    df1 = generate_synthetic_dataset(cfg1)
    df2 = generate_synthetic_dataset(cfg2)

    assert not df1["monthly_income"].equals(df2["monthly_income"])


def test_safe_formula_evaluator():
    test_df = pd.DataFrame({
        "savings": [100.0, 250.0, 500.0],
        "investments": [50.0, 100.0, 200.0],
        "risk": ["Conservative", "Moderate", "Aggressive"],
    })
    res_sum = evaluate_formula("savings + investments", test_df)
    assert list(res_sum) == [150.0, 350.0, 700.0]

    res_cond = evaluate_formula("1 if (savings > 200 and risk in ['Moderate', 'Aggressive']) else 0", test_df)
    assert list(res_cond) == [0, 1, 1]


def test_derived_financial_identities_hold(base_config):
    df = generate_synthetic_dataset(base_config)

    # Check Total Assets identity
    expected_assets = df["savings_balance"] + df["investment_portfolio_value"]
    np.testing.assert_allclose(df["total_financial_assets"], expected_assets, rtol=1e-3, atol=1e-2)

    # Check Allocation Identity
    alloc_sum = df["equity_allocation_pct"] + df["debt_allocation_pct"]
    np.testing.assert_allclose(alloc_sum, 100.0, rtol=1e-3, atol=1e-2)


def test_hard_bounds_enforced(base_config):
    df = generate_synthetic_dataset(base_config)
    assert (df["age"] >= 21).all()
    assert (df["age"] <= 72).all()
    assert (df["monthly_income"] >= 25000).all()
    assert (df["monthly_expenses"] >= 10000).all()


def test_noise_policy_protects_discrete_and_id_fields(base_config):
    df = generate_synthetic_dataset(base_config)

    # ID format unchanged
    assert df["customer_id"].str.startswith("CUST-FIN-").all()
    assert df["customer_id"].is_unique

    # Category choices valid
    allowed_genders = {"Female", "Male", "Other"}
    assert set(df["gender"].unique()).issubset(allowed_genders)


def test_generate_reproducible_script(base_config):
    script = generate_reproducible_script(base_config)
    assert "generate_synthetic_dataset" in script
    assert "CONFIG_JSON" in script
    assert "random_seed" in script


def test_generation_agriculture_domain_identities_and_noise():
    raw_agri = _get_mock_generation_config({
        "project_name": "Crop Yield Modeling",
        "domain": "Agriculture",
        "country": "Kenya",
        "record_count": 500,
        "random_seed": 77,
    })
    cfg_agri = GenerationConfig.from_dict(raw_agri)
    df = generate_synthetic_dataset(cfg_agri)

    assert len(df) == 500
    assert "monthly_income" not in df.columns
    assert "soil_ph" in df.columns
    assert "total_nutrients_ppm" in df.columns

    # Verify agronomic identity holds post-noise
    expected_nutrients = df["nitrogen_ppm"] + df["phosphorus_ppm"]
    np.testing.assert_allclose(df["total_nutrients_ppm"], expected_nutrients, rtol=1e-3, atol=1e-2)
    assert df["field_id"].str.startswith("PLOT-AG-").all()


def test_generation_healthcare_domain_identities():
    raw_hc = _get_mock_generation_config({
        "project_name": "Patient Vitals Profiling",
        "domain": "Healthcare",
        "country": "UK",
        "record_count": 500,
        "random_seed": 88,
    })
    cfg_hc = GenerationConfig.from_dict(raw_hc)
    df = generate_synthetic_dataset(cfg_hc)

    assert len(df) == 500
    assert "systolic_bp" in df.columns
    assert "pulse_pressure" in df.columns

    # Verify pulse pressure identity holds post-noise
    expected_pulse = df["systolic_bp"] - df["diastolic_bp"]
    np.testing.assert_allclose(df["pulse_pressure"], expected_pulse, rtol=1e-3, atol=1e-2)
    assert df["patient_id"].str.startswith("PAT-HC-").all()
