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

DEFAULT_MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    # Claude 3.5 Sonnet / Haiku models (8192 max output tokens)
    "claude-3-5-sonnet-20241022": 8192,
    "claude-3-5-sonnet-20240620": 8192,
    "claude-3-5-sonnet-latest": 8192,
    "claude-3-5-haiku-20241022": 8192,
    "claude-3-5-haiku-latest": 8192,
    # Claude 3.7 Sonnet models (up to 64000 max output tokens)
    "claude-3-7-sonnet-20250219": 64000,
    "claude-3-7-sonnet-latest": 64000,
    # Claude 3 Opus / Haiku / Sonnet (4096 max output tokens)
    "claude-3-opus-20240229": 4096,
    "claude-3-opus-latest": 4096,
    "claude-3-sonnet-20240229": 4096,
    "claude-3-haiku-20240307": 4096,
}

FALLBACK_MAX_OUTPUT_TOKENS = 8192


def get_model_token_ceiling(model_name: str | None = None) -> int:
    """Return the maximum supported output token limit for a given Anthropic model."""
    target = (model_name or os.getenv("ANTHROPIC_MODEL") or ANTHROPIC_MODEL or "claude-3-5-sonnet-20241022").strip().lower()
    for pattern, limit in DEFAULT_MODEL_MAX_OUTPUT_TOKENS.items():
        if pattern in target:
            return limit
    if "3-7" in target:
        return 64000
    if "3-5" in target:
        return 8192
    if "3" in target:
        return 4096
    return FALLBACK_MAX_OUTPUT_TOKENS


def get_max_tokens_for_task(task: str = "general", model_name: str | None = None) -> int:
    """
    Determine the optimal max_tokens parameter dynamically based on task requirements and model limits.
    If ANTHROPIC_MAX_TOKENS is explicitly set in .env, it is respected (capped at the model ceiling).
    Otherwise, automatically allocates high capacity for long tasks and minimal capacity for quick checks.
    """
    ceiling = get_model_token_ceiling(model_name)
    env_override = os.getenv("ANTHROPIC_MAX_TOKENS", "").strip()
    if env_override:
        try:
            val = int(env_override)
            if val > 0:
                return min(val, ceiling)
        except ValueError:
            pass

    if task == "connectivity_check":
        return 256
    elif task in ("specification", "generation_config", "large_generation"):
        return min(8192, ceiling)
    else:
        return min(8192, ceiling)


# Backward-compatible global token limit (resolved dynamically based on model)
ANTHROPIC_MAX_TOKENS = get_max_tokens_for_task("general", ANTHROPIC_MODEL)

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
    ANTHROPIC_MAX_TOKENS is optional; if provided, it must be a positive integer.
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

    raw_tokens = os.getenv("ANTHROPIC_MAX_TOKENS", "").strip()
    if raw_tokens:
        try:
            max_tokens = int(raw_tokens)
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
