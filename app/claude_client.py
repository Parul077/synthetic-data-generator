import json
import logging
import os
import re
import time
from typing import Any

import anthropic
from anthropic import Anthropic

from app.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MAX_TOKENS,
    ANTHROPIC_MODEL,
    PROMPTS_DIR,
    get_mock_mode,
    validate_config,
)
from app.schemas import GenerationConfig, SpecificationSuggestion

logger = logging.getLogger("synthetic_data_generator.claude")


def load_system_prompt(filename: str) -> str:
    """Load a system prompt from the prompts directory."""
    prompt_path = PROMPTS_DIR / filename
    if not prompt_path.is_file():
        raise FileNotFoundError(
            f"Required prompt file '{filename}' was not found at {prompt_path}. "
            "Please ensure the prompts directory contains the required files."
        )
    with open(prompt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        raise ValueError(f"Prompt file '{filename}' is empty.")
    return content


def create_client() -> Anthropic:
    """Create the official Anthropic API client."""
    validate_config()
    return Anthropic(
        api_key=ANTHROPIC_API_KEY,
        timeout=45.0,
        max_retries=2,
    )


def extract_json_from_text(text: str) -> Any:
    """Extract and parse JSON from Claude response, handling code fence blocks."""
    cleaned = text.strip()
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
    if code_block_match:
        cleaned = code_block_match.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        first_bracket = min(
            (pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos != -1),
            default=-1,
        )
        last_bracket = max(cleaned.rfind("}"), cleaned.rfind("]"))
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            substring = cleaned[first_bracket : last_bracket + 1]
            try:
                return json.loads(substring)
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"Claude returned invalid JSON: {exc}") from exc


def test_connection() -> str:
    """Send a minimal request to test Anthropic API connectivity or return mock confirmation."""
    if get_mock_mode():
        return json.dumps({
            "status": "ok",
            "mode": "mock",
            "message": "Mock mode active. No API key required.",
        })

    client = create_client()
    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": 'Return only this JSON object: {"status":"ok"}',
                }
            ],
        )

        text_blocks = [
            block.text
            for block in response.content
            if block.type == "text"
        ]

        if not text_blocks:
            raise RuntimeError("Claude returned no text response.")

        response_text = "\n".join(text_blocks).strip()
        parsed = extract_json_from_text(response_text)

        if not isinstance(parsed, dict) or parsed.get("status") != "ok":
            raise ValueError("Claude response did not match the expected JSON format.")

        return json.dumps(parsed)

    except anthropic.AuthenticationError as exc:
        raise RuntimeError(
            "Authentication failed. Check that your ANTHROPIC_API_KEY in .env is valid "
            "and that your account has available credits."
        ) from exc
    except anthropic.NotFoundError as exc:
        raise RuntimeError(
            f"The model '{ANTHROPIC_MODEL}' was not found. Check ANTHROPIC_MODEL in .env "
            "and verify your account has access to it."
        ) from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError(
            "Anthropic API rate limit or usage quota exceeded. Please wait before retrying."
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise RuntimeError(
            "Could not connect to Anthropic API. Check your internet connection or proxy settings."
        ) from exc
    except anthropic.APIStatusError as exc:
        raise RuntimeError(
            f"Anthropic API returned HTTP {exc.status_code}. Status: {exc.message}"
        ) from exc


def detect_domain_family(project_info: dict[str, Any]) -> str:
    """Detect the domain family from user project metadata."""
    combined = (
        f"{project_info.get('domain', '')} "
        f"{project_info.get('project_name', '')} "
        f"{project_info.get('dataset_objective', '')}"
    ).lower()

    if any(k in combined for k in ["agri", "crop", "soil", "farm", "yield", "harvest", "irrigation"]):
        return "agriculture"
    if any(k in combined for k in ["health", "patient", "clinic", "medic", "hospital", "disease", "vital"]):
        return "healthcare"
    if any(k in combined for k in ["retail", "store", "e-com", "churn", "shop", "merchandis", "sales"]):
        return "retail"
    if any(k in combined for k in ["edu", "student", "school", "academic", "course", "grade", "exam"]):
        return "education"
    if any(k in combined for k in ["manuf", "factory", "sensor", "telemetry", "machine", "defect", "equipment"]):
        return "manufacturing"
    if any(k in combined for k in ["financ", "invest", "bank", "wealth", "loan", "credit", "portfolio"]):
        return "finance"
    return "generic"


def _get_mock_specification_suggestions(
    workbook_metadata: dict[str, Any], project_info: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Dynamically generate domain-adapted mock specification suggestions
    based on the user's actual project definition.
    """
    sheets = workbook_metadata.get("sheet_names", ["Specification"])
    sheet = sheets[0] if sheets else "Specification"

    proj_name = project_info.get("project_name") or "Synthetic Dataset"
    domain = project_info.get("domain") or "General"
    country = project_info.get("country") or "Global"
    objective = project_info.get("dataset_objective") or "Generate representative synthetic observations."
    structure = project_info.get("data_structure") or "Tabular"
    rec_count = int(project_info.get("record_count") or 10000)
    domain_fam = detect_domain_family(project_info)

    base_items = [
        {
            "sheet_name": sheet,
            "cell": "B1",
            "field_name": "Project Name",
            "proposed_value": proj_name,
            "reasoning": f"Primary identifier for {domain} synthetic profiling.",
            "assumptions": "Confirmed project title from project definition.",
            "confidence": "HIGH",
            "source": "User Input",
            "needs_human_confirmation": False,
        },
        {
            "sheet_name": sheet,
            "cell": "B2",
            "field_name": "Record Count",
            "proposed_value": rec_count,
            "reasoning": f"Sample size required for statistically significant {domain} modeling.",
            "assumptions": f"Exact target of {rec_count:,} records.",
            "confidence": "HIGH",
            "source": "User Input",
            "needs_human_confirmation": False,
        },
        {
            "sheet_name": sheet,
            "cell": "B3",
            "field_name": "Country & Domain",
            "proposed_value": f"{country} - {domain}",
            "reasoning": "Establishes geographical jurisdiction and operational context.",
            "assumptions": f"Standards and measurement units aligned with {country} regulations.",
            "confidence": "HIGH",
            "source": "Domain Inference",
            "needs_human_confirmation": False,
        },
        {
            "sheet_name": sheet,
            "cell": "B4",
            "field_name": "Data Structure",
            "proposed_value": structure,
            "reasoning": f"{structure} data model aligned with project requirements.",
            "assumptions": "Entity-level observations at regular intervals or points in time.",
            "confidence": "HIGH",
            "source": "Architecture",
            "needs_human_confirmation": False,
        },
    ]

    # Domain-specific field specifications
    if domain_fam == "agriculture":
        domain_items = [
            {
                "sheet_name": sheet,
                "cell": "B6",
                "field_name": "Soil & Environmental Nutrients",
                "proposed_value": "soil_ph: 5.5-8.2; nitrogen_ppm: 80-260; rainfall_mm: 300-1400",
                "reasoning": "Realistic agronomic bounds for arable soil and seasonal precipitation.",
                "assumptions": "Reflects standard agricultural field chemistry and rainfall variations.",
                "confidence": "HIGH",
                "source": "Agronomic Standards",
                "needs_human_confirmation": True,
            },
            {
                "sheet_name": sheet,
                "cell": "B7",
                "field_name": "Total Nutrients Identity",
                "proposed_value": "total_nutrients_ppm == nitrogen_ppm + phosphorus_ppm",
                "reasoning": "Sum of primary macronutrient concentrations.",
                "assumptions": "Non-negative nutrient values; additive identity holds strictly.",
                "confidence": "HIGH",
                "source": "Soil Chemistry Identity",
                "needs_human_confirmation": False,
            },
            {
                "sheet_name": sheet,
                "cell": "B8",
                "field_name": "Target Variable: High Crop Yield Indicator",
                "proposed_value": "Binary flag (0/1) conditioned on optimal soil pH (6.0-7.5) and adequate rainfall (>500mm)",
                "reasoning": f"Directly satisfies objective: {objective}",
                "assumptions": "Yield propensity driven by favorable soil balance and water availability.",
                "confidence": "HIGH",
                "source": "Business Objective",
                "needs_human_confirmation": False,
            },
        ]
    elif domain_fam == "healthcare":
        domain_items = [
            {
                "sheet_name": sheet,
                "cell": "B6",
                "field_name": "Patient Clinical Vitals",
                "proposed_value": "Age: 18-85; Systolic BP: 90-190 mmHg; Diastolic BP: 60-120 mmHg; Fasting Glucose: 70-280 mg/dL",
                "reasoning": "Clinical distribution ranges for adult patient monitoring cohorts.",
                "assumptions": "Blood pressure and glucose follow adult clinical distribution profiles.",
                "confidence": "HIGH",
                "source": "Clinical Guidelines",
                "needs_human_confirmation": True,
            },
            {
                "sheet_name": sheet,
                "cell": "B7",
                "field_name": "Pulse Pressure Identity",
                "proposed_value": "pulse_pressure == systolic_bp - diastolic_bp; systolic_bp > diastolic_bp",
                "reasoning": "Standard physiological identity: pulse pressure is systolic minus diastolic pressure.",
                "assumptions": "Systolic strictly exceeds diastolic pressure by at least 15 mmHg.",
                "confidence": "HIGH",
                "source": "Physiological Law",
                "needs_human_confirmation": False,
            },
            {
                "sheet_name": sheet,
                "cell": "B8",
                "field_name": "Target Variable: Clinical Risk Flag",
                "proposed_value": "Binary indicator (0/1) for high clinical risk based on BP and glucose thresholds",
                "reasoning": f"Directly satisfies objective: {objective}",
                "assumptions": "Elevated risk when systolic > 140 or fasting glucose > 140 mg/dL.",
                "confidence": "HIGH",
                "source": "Business Objective",
                "needs_human_confirmation": False,
            },
        ]
    elif domain_fam == "retail":
        domain_items = [
            {
                "sheet_name": sheet,
                "cell": "B6",
                "field_name": "Customer Purchasing Behavior",
                "proposed_value": "Tenure: 1-120 months; Annual Spend: $200-$15,000; Returns Count: 0-25",
                "reasoning": "E-commerce and retail customer behavioral metrics.",
                "assumptions": "Spend follows right-skewed lognormal; tenure bounded up to 10 years.",
                "confidence": "HIGH",
                "source": "Retail Analytics",
                "needs_human_confirmation": True,
            },
            {
                "sheet_name": sheet,
                "cell": "B7",
                "field_name": "Net Spend Identity",
                "proposed_value": "net_annual_spend == gross_spend - refund_amount; net_annual_spend >= 0",
                "reasoning": "Financial accounting identity: net spend equals gross transactions minus refunds.",
                "assumptions": "Refunds cannot exceed gross spend.",
                "confidence": "HIGH",
                "source": "Accounting Rules",
                "needs_human_confirmation": False,
            },
            {
                "sheet_name": sheet,
                "cell": "B8",
                "field_name": "Target Variable: Churn Propensity",
                "proposed_value": "Binary flag (0/1) indicating customer churn risk based on tenure and visit recency",
                "reasoning": f"Directly satisfies objective: {objective}",
                "assumptions": "Lower tenure and high return ratios increase churn probability.",
                "confidence": "HIGH",
                "source": "Business Objective",
                "needs_human_confirmation": False,
            },
        ]
    elif domain_fam == "finance":
        domain_items = [
            {
                "sheet_name": sheet,
                "cell": "B6",
                "field_name": "Customer Demographics & Income",
                "proposed_value": "Age: 21-70, Income: Lognormal (mean 85,000, min 25,000, max 650,000)",
                "reasoning": "Retail investment banking demographic distribution profile.",
                "assumptions": "Income follows right-skewed distribution; age bounded between 21 and 70.",
                "confidence": "HIGH",
                "source": "Market Analysis",
                "needs_human_confirmation": True,
            },
            {
                "sheet_name": sheet,
                "cell": "B7",
                "field_name": "Financial Assets & Identities",
                "proposed_value": "total_financial_assets == savings_balance + investment_portfolio_value",
                "reasoning": "Strict accounting identity: total financial assets equals sum of component balances.",
                "assumptions": "Non-negative balances; additive accounting identity holds strictly.",
                "confidence": "HIGH",
                "source": "Accounting Rules",
                "needs_human_confirmation": False,
            },
            {
                "sheet_name": sheet,
                "cell": "B8",
                "field_name": "Target Variable: Investment Propensity",
                "proposed_value": "Binary flag (0/1) for high investment propensity conditioned on income and savings",
                "reasoning": f"Directly satisfies objective: {objective}",
                "assumptions": "Propensity positively correlated with income and risk tolerance.",
                "confidence": "HIGH",
                "source": "Business Objective",
                "needs_human_confirmation": False,
            },
        ]
    else:
        # Fully generic domain
        domain_items = [
            {
                "sheet_name": sheet,
                "cell": "B6",
                "field_name": f"{domain} Primary Attributes",
                "proposed_value": f"Continuous metrics (mean 100, min 10, max 1000) and categorical tiers tailored to {domain}",
                "reasoning": f"Standard parametric attributes for {domain} profile modeling.",
                "assumptions": f"Empirical distributions adapted to {domain} jurisdiction ({country}).",
                "confidence": "HIGH",
                "source": "Domain Inference",
                "needs_human_confirmation": True,
            },
            {
                "sheet_name": sheet,
                "cell": "B7",
                "field_name": "Composite Metric Identity",
                "proposed_value": "total_metric == component_a + component_b; component_a >= 0 and component_b >= 0",
                "reasoning": "Logical sum constraint connecting underlying sub-metrics.",
                "assumptions": "Additive identity holds strictly without distortion.",
                "confidence": "HIGH",
                "source": "System Identity",
                "needs_human_confirmation": False,
            },
            {
                "sheet_name": sheet,
                "cell": "B8",
                "field_name": "Target Outcome Variable",
                "proposed_value": f"Binary target indicator (0/1) aligned with: {objective}",
                "reasoning": f"Target column reflecting: {objective}",
                "assumptions": "Derived from core continuous predictors with realistic classification threshold.",
                "confidence": "HIGH",
                "source": "Business Objective",
                "needs_human_confirmation": False,
            },
        ]

    # Noise policy item
    noise_item = {
        "sheet_name": sheet,
        "cell": "B9",
        "field_name": "Noise Policy",
        "proposed_value": "15% bounded perturbation on continuous features; zero noise on categories, IDs, and identities",
        "reasoning": "Satisfies the 15% random noise mandate without violating hard constraints or formulas.",
        "assumptions": "15% refers to the proportion of eligible continuous feature cells perturbed.",
        "confidence": "HIGH",
        "source": "Noise Policy Spec",
        "needs_human_confirmation": False,
    }

    return base_items + domain_items + [noise_item]


def _get_mock_generation_config(project_info: dict[str, Any]) -> dict[str, Any]:
    """
    Dynamically generate a complete, valid GenerationConfig dictionary
    tailored to the user's specific domain and project definition.
    """
    rec_count = int(project_info.get("record_count") or 10000)
    seed = int(project_info.get("random_seed") if project_info.get("random_seed") is not None else 42)
    proj_name = project_info.get("project_name") or "Synthetic Dataset"
    domain = project_info.get("domain") or "General"
    country = project_info.get("country") or "Global"
    objective = project_info.get("dataset_objective") or "Generate representative synthetic observations."
    structure = project_info.get("data_structure") or "tabular"
    if isinstance(structure, str):
        structure = structure.lower()
    domain_fam = detect_domain_family(project_info)

    if domain_fam == "agriculture":
        return {
            "project_name": proj_name,
            "domain": domain,
            "country": country,
            "dataset_objective": objective,
            "data_structure": structure,
            "record_count": rec_count,
            "random_seed": seed,
            "columns": [
                {
                    "name": "field_id",
                    "data_type": "string",
                    "description": "Unique agricultural field / plot identifier",
                    "distribution": "id",
                    "params": {"prefix": "PLOT-AG-", "digits": 6},
                    "is_id": True,
                    "noise_eligible": False,
                },
                {
                    "name": "crop_type",
                    "data_type": "category",
                    "description": "Cultivated crop type",
                    "distribution": "categorical",
                    "params": {
                        "categories": ["Wheat", "Rice", "Maize", "Soybeans", "Pulses"],
                        "proportions": [0.30, 0.25, 0.20, 0.15, 0.10],
                    },
                    "noise_eligible": False,
                },
                {
                    "name": "soil_ph",
                    "data_type": "float",
                    "description": "Soil acidity / alkalinity level (pH)",
                    "distribution": "normal",
                    "params": {"mean": 6.8, "std": 0.6, "min": 5.0, "max": 8.5},
                    "hard_min": 4.5,
                    "hard_max": 9.0,
                    "noise_eligible": True,
                },
                {
                    "name": "nitrogen_ppm",
                    "data_type": "float",
                    "description": "Soil nitrogen concentration in parts per million",
                    "distribution": "normal",
                    "params": {"mean": 140.0, "std": 35.0, "min": 60.0, "max": 250.0},
                    "hard_min": 30.0,
                    "hard_max": 300.0,
                    "noise_eligible": True,
                },
                {
                    "name": "phosphorus_ppm",
                    "data_type": "float",
                    "description": "Soil phosphorus concentration in parts per million",
                    "distribution": "normal",
                    "params": {"mean": 45.0, "std": 15.0, "min": 15.0, "max": 90.0},
                    "hard_min": 10.0,
                    "hard_max": 120.0,
                    "noise_eligible": True,
                },
                {
                    "name": "total_nutrients_ppm",
                    "data_type": "float",
                    "description": "Combined macro-nutrient concentration (nitrogen + phosphorus)",
                    "distribution": "derived",
                    "is_derived": True,
                    "formula": "nitrogen_ppm + phosphorus_ppm",
                    "hard_min": 40.0,
                    "noise_eligible": False,
                },
                {
                    "name": "rainfall_mm",
                    "data_type": "float",
                    "description": "Seasonal rainfall accumulation in millimeters",
                    "distribution": "lognormal",
                    "params": {"mean": 650.0, "std": 200.0, "min": 250.0, "max": 1400.0},
                    "hard_min": 150.0,
                    "hard_max": 1800.0,
                    "noise_eligible": True,
                },
                {
                    "name": "fertilizer_kg_per_ha",
                    "data_type": "float",
                    "description": "Fertilizer application rate in kg per hectare",
                    "distribution": "normal",
                    "params": {"mean": 120.0, "std": 30.0, "min": 40.0, "max": 220.0},
                    "hard_min": 20.0,
                    "hard_max": 260.0,
                    "noise_eligible": True,
                },
                {
                    "name": "high_yield_target",
                    "data_type": "integer",
                    "description": "Target indicator: 1 if plot achieves high crop yield, 0 otherwise",
                    "distribution": "derived",
                    "is_target": True,
                    "is_derived": True,
                    "formula": "1 if (soil_ph >= 6.2 and soil_ph <= 7.5 and total_nutrients_ppm > 170.0 and rainfall_mm > 500.0) else 0",
                    "noise_eligible": False,
                },
            ],
            "constraints": [
                {
                    "name": "Total Nutrients Identity",
                    "type": "identity",
                    "columns": ["nitrogen_ppm", "phosphorus_ppm", "total_nutrients_ppm"],
                    "expression": "total_nutrients_ppm == nitrogen_ppm + phosphorus_ppm",
                    "description": "Total nutrient concentration must equal nitrogen plus phosphorus.",
                },
                {
                    "name": "Non-Negative Soil & Rain Metrics",
                    "type": "non_negative",
                    "columns": ["nitrogen_ppm", "phosphorus_ppm", "rainfall_mm", "fertilizer_kg_per_ha"],
                    "expression": "all >= 0",
                    "description": "Physical chemical and weather quantities cannot be negative.",
                },
            ],
            "correlations": [
                {"col1": "nitrogen_ppm", "col2": "fertilizer_kg_per_ha", "target_corr": 0.60, "tolerance": 0.20},
                {"col1": "rainfall_mm", "col2": "total_nutrients_ppm", "target_corr": 0.35, "tolerance": 0.20},
            ],
            "noise_policy": {
                "percentage": 0.15,
                "strategy": "gaussian_perturbation",
                "perturbation_scale": 0.10,
                "eligible_columns": ["soil_ph", "nitrogen_ppm", "phosphorus_ppm", "rainfall_mm", "fertilizer_kg_per_ha"],
                "excluded_columns": ["field_id", "crop_type", "total_nutrients_ppm", "high_yield_target"],
                "description": "15% bounded perturbation on continuous agronomic metrics.",
            },
            "longitudinal_periods": 1,
            "customer_id_col": "field_id",
            "output_formats": ["csv", "xlsx", "json"],
            "validation_tolerances": {"row_count_tolerance": 0.0, "correlation_tolerance": 0.20},
            "assumptions": [f"Agricultural parameters tailored to {country} arable farming practices.", "Soil nutrient identities strictly preserved post-noise."],
        }

    elif domain_fam == "healthcare":
        return {
            "project_name": proj_name,
            "domain": domain,
            "country": country,
            "dataset_objective": objective,
            "data_structure": structure,
            "record_count": rec_count,
            "random_seed": seed,
            "columns": [
                {
                    "name": "patient_id",
                    "data_type": "string",
                    "description": "Anonymized unique patient identifier",
                    "distribution": "id",
                    "params": {"prefix": "PAT-HC-", "digits": 6},
                    "is_id": True,
                    "noise_eligible": False,
                },
                {
                    "name": "age",
                    "data_type": "integer",
                    "description": "Patient age in years",
                    "distribution": "normal",
                    "params": {"mean": 48.0, "std": 14.0, "min": 18, "max": 85},
                    "hard_min": 18.0,
                    "hard_max": 90.0,
                    "noise_eligible": True,
                },
                {
                    "name": "gender",
                    "data_type": "category",
                    "description": "Patient biological sex",
                    "distribution": "categorical",
                    "params": {"categories": ["Female", "Male", "Other"], "proportions": [0.50, 0.48, 0.02]},
                    "noise_eligible": False,
                },
                {
                    "name": "systolic_bp",
                    "data_type": "float",
                    "description": "Systolic blood pressure in mmHg",
                    "distribution": "normal",
                    "params": {"mean": 128.0, "std": 18.0, "min": 95.0, "max": 185.0},
                    "hard_min": 85.0,
                    "hard_max": 200.0,
                    "noise_eligible": True,
                },
                {
                    "name": "diastolic_bp",
                    "data_type": "float",
                    "description": "Diastolic blood pressure in mmHg",
                    "distribution": "normal",
                    "params": {"mean": 82.0, "std": 11.0, "min": 60.0, "max": 115.0},
                    "hard_min": 50.0,
                    "hard_max": 130.0,
                    "noise_eligible": True,
                },
                {
                    "name": "pulse_pressure",
                    "data_type": "float",
                    "description": "Pulse pressure (systolic_bp - diastolic_bp)",
                    "distribution": "derived",
                    "is_derived": True,
                    "formula": "systolic_bp - diastolic_bp",
                    "noise_eligible": False,
                },
                {
                    "name": "fasting_glucose_mg_dl",
                    "data_type": "float",
                    "description": "Fasting blood glucose level in mg/dL",
                    "distribution": "lognormal",
                    "params": {"mean": 105.0, "std": 30.0, "min": 65.0, "max": 260.0},
                    "hard_min": 60.0,
                    "hard_max": 300.0,
                    "noise_eligible": True,
                },
                {
                    "name": "clinical_risk_target",
                    "data_type": "integer",
                    "description": "Target indicator: 1 if high clinical cardiovascular risk, 0 otherwise",
                    "distribution": "derived",
                    "is_target": True,
                    "is_derived": True,
                    "formula": "1 if (systolic_bp > 140.0 or fasting_glucose_mg_dl > 125.0 or pulse_pressure > 55.0) else 0",
                    "noise_eligible": False,
                },
            ],
            "constraints": [
                {
                    "name": "Pulse Pressure Identity",
                    "type": "identity",
                    "columns": ["systolic_bp", "diastolic_bp", "pulse_pressure"],
                    "expression": "pulse_pressure == systolic_bp - diastolic_bp",
                    "description": "Pulse pressure must equal systolic minus diastolic blood pressure.",
                },
                {
                    "name": "Systolic Exceeds Diastolic",
                    "type": "inequality",
                    "columns": ["systolic_bp", "diastolic_bp"],
                    "expression": "systolic_bp > diastolic_bp",
                    "description": "Systolic blood pressure must exceed diastolic blood pressure.",
                },
            ],
            "correlations": [
                {"col1": "age", "col2": "systolic_bp", "target_corr": 0.55, "tolerance": 0.20},
                {"col1": "systolic_bp", "col2": "diastolic_bp", "target_corr": 0.65, "tolerance": 0.20},
            ],
            "noise_policy": {
                "percentage": 0.15,
                "strategy": "gaussian_perturbation",
                "perturbation_scale": 0.08,
                "eligible_columns": ["age", "systolic_bp", "diastolic_bp", "fasting_glucose_mg_dl"],
                "excluded_columns": ["patient_id", "gender", "pulse_pressure", "clinical_risk_target"],
                "description": "15% bounded perturbation on continuous clinical metrics.",
            },
            "longitudinal_periods": 1,
            "customer_id_col": "patient_id",
            "output_formats": ["csv", "xlsx", "json"],
            "validation_tolerances": {"row_count_tolerance": 0.0, "correlation_tolerance": 0.20},
            "assumptions": [f"Patient cohort clinical indicators calibrated for {country} healthcare guidelines.", "Pulse pressure identity holds strictly."],
        }

    elif domain_fam == "retail":
        return {
            "project_name": proj_name,
            "domain": domain,
            "country": country,
            "dataset_objective": objective,
            "data_structure": structure,
            "record_count": rec_count,
            "random_seed": seed,
            "columns": [
                {
                    "name": "customer_id",
                    "data_type": "string",
                    "description": "Retail customer identifier",
                    "distribution": "id",
                    "params": {"prefix": "CUST-RET-", "digits": 6},
                    "is_id": True,
                    "noise_eligible": False,
                },
                {
                    "name": "tenure_months",
                    "data_type": "integer",
                    "description": "Customer account age in months",
                    "distribution": "uniform",
                    "params": {"min": 1, "max": 96},
                    "hard_min": 1.0,
                    "hard_max": 120.0,
                    "noise_eligible": True,
                },
                {
                    "name": "loyalty_tier",
                    "data_type": "category",
                    "description": "Customer rewards membership tier",
                    "distribution": "categorical",
                    "params": {"categories": ["Bronze", "Silver", "Gold", "Platinum"], "proportions": [0.45, 0.30, 0.18, 0.07]},
                    "noise_eligible": False,
                },
                {
                    "name": "gross_annual_spend",
                    "data_type": "float",
                    "description": "Total gross order volume before refunds in local currency",
                    "distribution": "lognormal",
                    "params": {"mean": 2400.0, "std": 1800.0, "min": 150.0, "max": 18000.0},
                    "hard_min": 100.0,
                    "hard_max": 25000.0,
                    "noise_eligible": True,
                },
                {
                    "name": "refund_amount",
                    "data_type": "float",
                    "description": "Value of merchandise returns and refunds in local currency",
                    "distribution": "normal",
                    "params": {"mean": 180.0, "std": 140.0, "min": 0.0, "max": 1200.0},
                    "hard_min": 0.0,
                    "hard_max": 3000.0,
                    "noise_eligible": True,
                },
                {
                    "name": "net_annual_spend",
                    "data_type": "float",
                    "description": "Net realized spend (gross_annual_spend - refund_amount)",
                    "distribution": "derived",
                    "is_derived": True,
                    "formula": "gross_annual_spend - refund_amount",
                    "hard_min": 50.0,
                    "noise_eligible": False,
                },
                {
                    "name": "churn_risk_target",
                    "data_type": "integer",
                    "description": "Target indicator: 1 if customer is at high risk of churn, 0 otherwise",
                    "distribution": "derived",
                    "is_target": True,
                    "is_derived": True,
                    "formula": "1 if (tenure_months < 12 and refund_amount > 250.0) else 0",
                    "noise_eligible": False,
                },
            ],
            "constraints": [
                {
                    "name": "Net Spend Identity",
                    "type": "identity",
                    "columns": ["gross_annual_spend", "refund_amount", "net_annual_spend"],
                    "expression": "net_annual_spend == gross_annual_spend - refund_amount",
                    "description": "Net annual spend must equal gross spend minus refunds.",
                },
                {
                    "name": "Refund Does Not Exceed Gross Spend",
                    "type": "inequality",
                    "columns": ["gross_annual_spend", "refund_amount"],
                    "expression": "refund_amount < gross_annual_spend",
                    "description": "Refund amount cannot exceed gross transaction value.",
                },
            ],
            "correlations": [
                {"col1": "tenure_months", "col2": "gross_annual_spend", "target_corr": 0.50, "tolerance": 0.20},
            ],
            "noise_policy": {
                "percentage": 0.15,
                "strategy": "gaussian_perturbation",
                "perturbation_scale": 0.10,
                "eligible_columns": ["tenure_months", "gross_annual_spend", "refund_amount"],
                "excluded_columns": ["customer_id", "loyalty_tier", "net_annual_spend", "churn_risk_target"],
                "description": "15% bounded perturbation on continuous retail metrics.",
            },
            "longitudinal_periods": 1,
            "customer_id_col": "customer_id",
            "output_formats": ["csv", "xlsx", "json"],
            "validation_tolerances": {"row_count_tolerance": 0.0, "correlation_tolerance": 0.20},
            "assumptions": [f"Retail transaction metrics reflect consumer behaviors in {country}.", "Net spend identity holds strictly."],
        }

    elif domain_fam == "finance":
        return {
            "project_name": proj_name,
            "domain": domain,
            "country": country,
            "dataset_objective": objective,
            "data_structure": structure,
            "record_count": rec_count,
            "random_seed": seed,
            "columns": [
                {
                    "name": "customer_id",
                    "data_type": "string",
                    "description": "Unique customer identifier",
                    "distribution": "id",
                    "params": {"prefix": "CUST-FIN-", "digits": 6},
                    "is_id": True,
                    "noise_eligible": False,
                },
                {
                    "name": "age",
                    "data_type": "integer",
                    "description": "Customer age in years",
                    "distribution": "normal",
                    "params": {"mean": 41.5, "std": 10.5, "min": 21, "max": 72},
                    "hard_min": 21.0,
                    "hard_max": 72.0,
                    "noise_eligible": True,
                },
                {
                    "name": "gender",
                    "data_type": "category",
                    "description": "Customer gender",
                    "distribution": "categorical",
                    "params": {"categories": ["Female", "Male", "Other"], "proportions": [0.46, 0.52, 0.02]},
                    "noise_eligible": False,
                },
                {
                    "name": "monthly_income",
                    "data_type": "float",
                    "description": "Net monthly income",
                    "distribution": "lognormal",
                    "params": {"mean": 95000, "std": 55000, "min": 25000, "max": 650000},
                    "hard_min": 25000.0,
                    "hard_max": 650000.0,
                    "noise_eligible": True,
                },
                {
                    "name": "monthly_expenses",
                    "data_type": "float",
                    "description": "Estimated monthly living expenses",
                    "distribution": "normal",
                    "params": {"mean": 42000, "std": 20000, "min": 12000, "max": 300000},
                    "hard_min": 10000.0,
                    "hard_max": 350000.0,
                    "noise_eligible": True,
                },
                {
                    "name": "savings_balance",
                    "data_type": "float",
                    "description": "Current balance in liquid savings and deposits",
                    "distribution": "lognormal",
                    "params": {"mean": 380000, "std": 280000, "min": 10000, "max": 4500000},
                    "hard_min": 5000.0,
                    "hard_max": 5000000.0,
                    "noise_eligible": True,
                },
                {
                    "name": "investment_portfolio_value",
                    "data_type": "float",
                    "description": "Current market value of investment portfolio",
                    "distribution": "lognormal",
                    "params": {"mean": 620000, "std": 480000, "min": 0, "max": 9000000},
                    "hard_min": 0.0,
                    "hard_max": 10000000.0,
                    "noise_eligible": True,
                },
                {
                    "name": "total_financial_assets",
                    "data_type": "float",
                    "description": "Total assets (savings_balance + investment_portfolio_value)",
                    "distribution": "derived",
                    "is_derived": True,
                    "formula": "savings_balance + investment_portfolio_value",
                    "hard_min": 5000.0,
                    "noise_eligible": False,
                },
                {
                    "name": "risk_tolerance",
                    "data_type": "category",
                    "description": "Assessed client risk profile",
                    "distribution": "categorical",
                    "params": {"categories": ["Conservative", "Moderate", "Aggressive"], "proportions": [0.28, 0.48, 0.24]},
                    "noise_eligible": False,
                },
                {
                    "name": "equity_allocation_pct",
                    "data_type": "float",
                    "description": "Portfolio share allocated to equities (0-100%)",
                    "distribution": "normal",
                    "params": {"mean": 52.0, "std": 22.0, "min": 0.0, "max": 100.0},
                    "hard_min": 0.0,
                    "hard_max": 100.0,
                    "noise_eligible": True,
                },
                {
                    "name": "debt_allocation_pct",
                    "data_type": "float",
                    "description": "Portfolio share allocated to debt instruments (100 - equity_allocation_pct)",
                    "distribution": "derived",
                    "is_derived": True,
                    "formula": "100.0 - equity_allocation_pct",
                    "hard_min": 0.0,
                    "hard_max": 100.0,
                    "noise_eligible": False,
                },
                {
                    "name": "investment_experience_years",
                    "data_type": "integer",
                    "description": "Years of investing experience",
                    "distribution": "normal",
                    "params": {"mean": 6.8, "std": 4.5, "min": 0, "max": 35},
                    "hard_min": 0.0,
                    "hard_max": 40.0,
                    "noise_eligible": True,
                },
                {
                    "name": "propensity_to_increase_investment",
                    "data_type": "integer",
                    "description": "Target indicator for propensity to increase investments",
                    "distribution": "derived",
                    "is_target": True,
                    "is_derived": True,
                    "formula": "1 if (monthly_income > 75000 and savings_balance > 200000 and risk_tolerance in ['Moderate', 'Aggressive'] and investment_experience_years >= 2) else 0",
                    "noise_eligible": False,
                },
            ],
            "constraints": [
                {
                    "name": "Total Assets Identity",
                    "type": "identity",
                    "columns": ["savings_balance", "investment_portfolio_value", "total_financial_assets"],
                    "expression": "total_financial_assets == savings_balance + investment_portfolio_value",
                    "description": "Total financial assets must equal savings plus investment portfolio value.",
                },
                {
                    "name": "Allocation Balance Identity",
                    "type": "identity",
                    "columns": ["equity_allocation_pct", "debt_allocation_pct"],
                    "expression": "equity_allocation_pct + debt_allocation_pct == 100.0",
                    "description": "Equity and debt allocation percentages must sum to 100%.",
                },
                {
                    "name": "Non-Negative Balances",
                    "type": "non_negative",
                    "columns": ["monthly_income", "monthly_expenses", "savings_balance", "investment_portfolio_value"],
                    "expression": "all >= 0",
                    "description": "Monetary values cannot be negative.",
                },
                {
                    "name": "Experience Bounded by Age",
                    "type": "inequality",
                    "columns": ["age", "investment_experience_years"],
                    "expression": "investment_experience_years <= age - 18",
                    "description": "Investment experience years cannot exceed adulthood span.",
                },
            ],
            "correlations": [
                {"col1": "monthly_income", "col2": "savings_balance", "target_corr": 0.62, "tolerance": 0.18},
                {"col1": "monthly_income", "col2": "investment_portfolio_value", "target_corr": 0.58, "tolerance": 0.18},
                {"col1": "age", "col2": "investment_experience_years", "target_corr": 0.70, "tolerance": 0.18},
            ],
            "noise_policy": {
                "percentage": 0.15,
                "strategy": "gaussian_perturbation",
                "perturbation_scale": 0.10,
                "eligible_columns": ["age", "monthly_income", "monthly_expenses", "savings_balance", "investment_portfolio_value", "equity_allocation_pct", "investment_experience_years"],
                "excluded_columns": ["customer_id", "gender", "risk_tolerance", "total_financial_assets", "debt_allocation_pct", "propensity_to_increase_investment"],
                "description": "15% bounded perturbation on continuous features.",
            },
            "longitudinal_periods": 1,
            "customer_id_col": "customer_id",
            "output_formats": ["csv", "xlsx", "json"],
            "validation_tolerances": {"row_count_tolerance": 0.0, "correlation_tolerance": 0.20},
            "assumptions": [f"Profiles calibrated for {country} retail investment banking.", "Accounting identities hold strictly."],
        }

    else:
        # Fully generic custom domain
        return {
            "project_name": proj_name,
            "domain": domain,
            "country": country,
            "dataset_objective": objective,
            "data_structure": structure,
            "record_count": rec_count,
            "random_seed": seed,
            "columns": [
                {
                    "name": "record_id",
                    "data_type": "string",
                    "description": f"Unique record identifier for {domain}",
                    "distribution": "id",
                    "params": {"prefix": "REC-", "digits": 6},
                    "is_id": True,
                    "noise_eligible": False,
                },
                {
                    "name": "category_segment",
                    "data_type": "category",
                    "description": f"Operational category tier for {domain}",
                    "distribution": "categorical",
                    "params": {"categories": ["Segment_A", "Segment_B", "Segment_C"], "proportions": [0.50, 0.35, 0.15]},
                    "noise_eligible": False,
                },
                {
                    "name": "primary_metric",
                    "data_type": "float",
                    "description": f"Primary continuous operational metric for {domain}",
                    "distribution": "normal",
                    "params": {"mean": 100.0, "std": 25.0, "min": 20.0, "max": 250.0},
                    "hard_min": 10.0,
                    "hard_max": 300.0,
                    "noise_eligible": True,
                },
                {
                    "name": "secondary_metric",
                    "data_type": "float",
                    "description": f"Secondary continuous operational metric for {domain}",
                    "distribution": "normal",
                    "params": {"mean": 50.0, "std": 15.0, "min": 10.0, "max": 120.0},
                    "hard_min": 5.0,
                    "hard_max": 150.0,
                    "noise_eligible": True,
                },
                {
                    "name": "composite_total_metric",
                    "data_type": "float",
                    "description": "Derived total (primary_metric + secondary_metric)",
                    "distribution": "derived",
                    "is_derived": True,
                    "formula": "primary_metric + secondary_metric",
                    "hard_min": 15.0,
                    "noise_eligible": False,
                },
                {
                    "name": "target_outcome",
                    "data_type": "integer",
                    "description": f"Target binary outcome indicator aligned with: {objective}",
                    "distribution": "derived",
                    "is_target": True,
                    "is_derived": True,
                    "formula": "1 if (primary_metric > 110.0 and composite_total_metric > 160.0) else 0",
                    "noise_eligible": False,
                },
            ],
            "constraints": [
                {
                    "name": "Composite Total Identity",
                    "type": "identity",
                    "columns": ["primary_metric", "secondary_metric", "composite_total_metric"],
                    "expression": "composite_total_metric == primary_metric + secondary_metric",
                    "description": "Composite total must equal primary plus secondary metric.",
                },
                {
                    "name": "Non-Negative Metrics",
                    "type": "non_negative",
                    "columns": ["primary_metric", "secondary_metric"],
                    "expression": "all >= 0",
                    "description": "Continuous metrics cannot be negative.",
                },
            ],
            "correlations": [
                {"col1": "primary_metric", "col2": "secondary_metric", "target_corr": 0.45, "tolerance": 0.20},
            ],
            "noise_policy": {
                "percentage": 0.15,
                "strategy": "gaussian_perturbation",
                "perturbation_scale": 0.10,
                "eligible_columns": ["primary_metric", "secondary_metric"],
                "excluded_columns": ["record_id", "category_segment", "composite_total_metric", "target_outcome"],
                "description": f"15% bounded perturbation on continuous {domain} metrics.",
            },
            "longitudinal_periods": 1,
            "customer_id_col": "record_id",
            "output_formats": ["csv", "xlsx", "json"],
            "validation_tolerances": {"row_count_tolerance": 0.0, "correlation_tolerance": 0.20},
            "assumptions": [f"Parameters generated dynamically for {domain} in {country}.", "Composite identity holds strictly."],
        }


def propose_specification(
    workbook_metadata: dict[str, Any], project_info: dict[str, Any]
) -> list[dict[str, Any]]:
    """
    Request Claude (or deterministic mock) to propose specification entries for the workbook.
    """
    if get_mock_mode():
        return _get_mock_specification_suggestions(workbook_metadata, project_info)

    system_prompt = load_system_prompt("specification_system.txt")
    client = create_client()

    compact_metadata = {
        "sheet_names": workbook_metadata.get("sheet_names", []),
        "sheet_count": workbook_metadata.get("sheet_count", 0),
        "sheets": [
            {
                "name": s["name"],
                "max_row": s["max_row"],
                "max_column": s["max_column"],
                "merged_cells": s.get("merged_cells", []),
                "formulas": s.get("formulas", []),
                "populated_cells": [
                    {"cell": c["cell"], "value": str(c["value"])[:100]}
                    for c in s.get("populated_cells", [])[:50]
                ],
            }
            for s in workbook_metadata.get("sheets", [])
        ],
    }

    user_prompt = f"""
Project Details:
- Name: {project_info.get('project_name', 'Synthetic Dataset')}
- Domain / Industry: {project_info.get('domain', 'General')}
- Country / Jurisdiction: {project_info.get('country', 'Global')}
- Objective: {project_info.get('dataset_objective', 'Generate representative synthetic data.')}
- Data Structure: {project_info.get('data_structure', 'Tabular')}
- Record Count: {project_info.get('record_count', 10000)}
- Random Seed: {project_info.get('random_seed', 42)}
- Additional Requirements / Business Rules: {project_info.get('additional_requirements', 'None specified')}

Workbook Inspection Metadata:
{json.dumps(compact_metadata, indent=2)}

Please inspect the workbook structure and propose field entries for the blank input cells based strictly on this specific project domain and objective.
Return ONLY a valid JSON list of objects matching this exact structure:
[
  {{
    "sheet_name": "<exact sheet title>",
    "cell": "<cell coordinate e.g. B1>",
    "field_name": "<description/label>",
    "proposed_value": "<value to enter>",
    "reasoning": "<justification>",
    "assumptions": "<underlying assumptions>",
    "confidence": "HIGH" | "MEDIUM" | "LOW",
    "source": "<source of requirement>",
    "needs_human_confirmation": true | false
  }}
]
"""

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = "\n".join(b.text for b in response.content if b.type == "text")
        parsed = extract_json_from_text(text)

        if not isinstance(parsed, list):
            raise ValueError("Claude response must be a JSON array of suggestions.")

        return parsed

    except anthropic.AuthenticationError as exc:
        raise RuntimeError(f"Anthropic authentication failed: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Anthropic rate limit reached. Please wait before retrying.") from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc}") from exc


def propose_generation_config(
    workbook_metadata: dict[str, Any],
    approved_specs: list[dict[str, Any]],
    project_info: dict[str, Any],
) -> dict[str, Any]:
    """
    Request Claude (or deterministic mock) to propose the full GenerationConfig.
    """
    if get_mock_mode():
        return _get_mock_generation_config(project_info)

    system_prompt = load_system_prompt("generation_system.txt")
    client = create_client()

    user_prompt = f"""
Approved Specification Items:
{json.dumps(approved_specs, indent=2, default=str)}

Project Metadata:
{json.dumps(project_info, indent=2)}

Generate a complete, valid JSON configuration adhering to the GenerationConfig schema strictly tailored to the specified domain ({project_info.get('domain')}) and project ({project_info.get('project_name')}):
- project_name, domain, country, dataset_objective, data_structure, record_count, random_seed
- columns: array of column objects with name, data_type, distribution, params, is_id, is_target, is_derived, formula, hard_min, hard_max, noise_eligible
- constraints: array of business rules and accounting identities
- correlations: array of expected continuous feature correlations
- noise_policy: percentage (0.15), strategy, eligible_columns, excluded_columns, description
- validation_tolerances

Return ONLY the JSON object. Do not include markdown or explanations outside the JSON.
"""

    try:
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = "\n".join(b.text for b in response.content if b.type == "text")
        parsed = extract_json_from_text(text)

        if not isinstance(parsed, dict):
            raise ValueError("Claude response must be a JSON object representing GenerationConfig.")

        return parsed

    except anthropic.AuthenticationError as exc:
        raise RuntimeError(f"Anthropic authentication failed: {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise RuntimeError("Anthropic rate limit reached. Please wait before retrying.") from exc
    except anthropic.APIError as exc:
        raise RuntimeError(f"Anthropic API error: {exc}") from exc
