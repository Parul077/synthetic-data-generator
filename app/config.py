import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_mock_mode() -> bool:
    """Return True if Claude mock mode is enabled."""
    val = os.getenv("CLAUDE_MOCK_MODE", "false").strip().lower()
    return val in {"true", "1", "yes", "on"}


ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip()

try:
    ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
except ValueError:
    ANTHROPIC_MAX_TOKENS = 4096

CLAUDE_MOCK_MODE = get_mock_mode()

OUTPUT_DIR = PROJECT_ROOT / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PROMPTS_DIR = PROJECT_ROOT / "prompts"


def is_placeholder_key(key: str) -> bool:
    """Check if the provided key is an empty or placeholder value."""
    if not key:
        return True
    placeholder_tokens = {"your_api_key_here", "sk-ant-placeholder", "none", "xxx"}
    return key.lower().strip() in placeholder_tokens or key.startswith("your_api")


def validate_config() -> None:
    """
    Validate Anthropic API settings.
    In mock mode, no key is needed.
    In live mode, a valid non-placeholder API key and model are required.
    """
    current_mock = get_mock_mode()
    if current_mock:
        return

    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if is_placeholder_key(key):
        raise ValueError(
            "ANTHROPIC_API_KEY is missing or contains placeholder text. "
            "Please add a valid Anthropic API key to your .env file, "
            "or set CLAUDE_MOCK_MODE=true for offline development/testing."
        )

    model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022").strip()
    if not model:
        raise ValueError("ANTHROPIC_MODEL cannot be empty.")

    try:
        max_tokens = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))
        if max_tokens < 1:
            raise ValueError()
    except ValueError:
        raise ValueError("ANTHROPIC_MAX_TOKENS must be a positive integer.")


# Pre-defined domain presets for quick start (users can also select Custom / Blank)
DOMAIN_PRESETS: dict[str, dict[str, Any]] = {
    "Custom / Blank Project": {
        "project_name": "",
        "domain": "",
        "country": "",
        "dataset_objective": "",
        "data_structure": "tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "",
    },
    "Financial Services: Investment Customer Data": {
        "project_name": "Investment Customer / Client Data",
        "domain": "Financial services",
        "country": "India",
        "dataset_objective": "Identify customers likely to increase their investments in equity or debt instruments.",
        "data_structure": "tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "Total financial assets equals savings plus investments. 15% bounded noise on continuous features.",
    },
    "Healthcare: Patient Clinical Vitals & Outcomes": {
        "project_name": "Patient Clinical Vitals & Risk Profiling",
        "domain": "Healthcare",
        "country": "United Kingdom",
        "dataset_objective": "Predict elevated cardiovascular risk based on systolic and diastolic blood pressure, pulse pressure, and fasting glucose.",
        "data_structure": "tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "Systolic blood pressure strictly exceeds diastolic pressure. Pulse pressure equals systolic minus diastolic.",
    },
    "Agriculture: Crop Yield & Soil Nutrients": {
        "project_name": "Arable Crop Yield & Soil Chemistry",
        "domain": "Agriculture",
        "country": "Kenya",
        "dataset_objective": "Model crop yield outcomes as a function of soil pH, nitrogen and phosphorus concentrations, and seasonal rainfall.",
        "data_structure": "tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "Total nutrients equals nitrogen plus phosphorus. Soil pH must stay bounded between 4.5 and 9.0.",
    },
    "Retail: Customer Lifetime Value & Churn Risk": {
        "project_name": "Retail E-Commerce Customer Churn",
        "domain": "Retail & E-Commerce",
        "country": "United States",
        "dataset_objective": "Analyze customer retention and churn risk using tenure, transaction volume, refund rates, and membership tiers.",
        "data_structure": "tabular",
        "record_count": 10000,
        "random_seed": 42,
        "additional_requirements": "Net annual spend equals gross spend minus refunds. Refunds cannot exceed gross spend.",
    },
}
