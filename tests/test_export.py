import zipfile
from io import BytesIO

import pandas as pd
import pytest

from app.claude_client import _get_mock_generation_config
from app.export import build_all_deliverables, sanitize_filename, save_deliverables_to_disk
from app.generation import generate_synthetic_dataset
from app.schemas import GenerationConfig
from app.validation import validate_dataset


@pytest.fixture
def test_setup():
    raw = _get_mock_generation_config({
        "project_name": "Investment Customer / Client Data",
        "record_count": 100,
        "random_seed": 42,
    })
    cfg = GenerationConfig.from_dict(raw)
    df = generate_synthetic_dataset(cfg)
    report = validate_dataset(df, cfg)
    return cfg, df, report


def test_sanitize_filename():
    assert sanitize_filename("Investment Customer / Client Data") == "Investment_Customer_Client_Data"
    assert sanitize_filename("../../../bad/path:file*?.csv") == "badpathfile.csv"
    assert sanitize_filename("") == "deliverable"


def test_build_all_deliverables_creates_all_files(test_setup):
    cfg, df, report = test_setup
    deliverables = build_all_deliverables(cfg, df, report, completed_workbook_bytes=b"sample_xlsx_bytes")

    # Check key files exist
    assert any(k.endswith(".csv") for k in deliverables)
    assert any(k.endswith(".xlsx") for k in deliverables)
    assert "generate_dataset.py" in deliverables
    assert any(k.endswith("_documentation.docx") for k in deliverables)
    assert any(k.endswith("_validation_report.docx") for k in deliverables)
    assert any(k.endswith("_validation_report.pdf") for k in deliverables)
    assert any(k.endswith("_assumptions_and_limitations.md") for k in deliverables)
    assert "generation_config.json" in deliverables
    assert "validation_results.json" in deliverables
    assert "generation_metadata.json" in deliverables
    assert any(k.endswith("_deliverables.zip") for k in deliverables)

    # Check all byte streams have positive size
    for fname, fbytes in deliverables.items():
        assert len(fbytes) > 0, f"Deliverable {fname} is empty"

    # Verify zip archive integrity
    zip_key = next(k for k in deliverables if k.endswith("_deliverables.zip"))
    zip_bytes = deliverables[zip_key]
    with zipfile.ZipFile(BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        assert len(names) >= 10
        assert "generate_dataset.py" in names


def test_save_deliverables_to_disk(tmp_path, test_setup):
    cfg, df, report = test_setup
    deliverables = build_all_deliverables(cfg, df, report)
    saved = save_deliverables_to_disk(deliverables, target_dir=tmp_path)
    assert len(saved) == len(deliverables)
    for p in saved:
        assert p.exists()
        assert p.stat().st_size > 0
