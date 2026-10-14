import json
import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from app.config import OUTPUT_DIR
from app.documentation import (
    generate_assumptions_and_limitations_md,
    generate_dataset_documentation_docx,
    generate_validation_report_docx,
    generate_validation_report_pdf,
)
from app.generation import generate_reproducible_script
from app.schemas import GenerationConfig, ValidationReport

logger = logging.getLogger("synthetic_data_generator.export")


def sanitize_filename(name: str) -> str:
    """Sanitize a string for safe usage in filenames."""
    s = re.sub(r'[\\/*?:"<>|]', "", name)
    s = re.sub(r"\.\.+", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s[:60] if s else "deliverable"


def build_all_deliverables(
    config: GenerationConfig,
    df: pd.DataFrame,
    report: ValidationReport,
    completed_workbook_bytes: bytes | None = None,
) -> dict[str, bytes]:
    """
    Generate in-memory byte contents for all 12 deliverables.
    Returns a dictionary mapping filename to bytes.
    """
    base_name = sanitize_filename(config.project_name)
    deliverables: dict[str, bytes] = {}

    # 1. Completed specification workbook (.xlsx)
    if completed_workbook_bytes:
        deliverables[f"{base_name}_specification.xlsx"] = completed_workbook_bytes

    # 2. Synthetic dataset (.csv)
    csv_bio = BytesIO()
    df.to_csv(csv_bio, index=False)
    deliverables[f"{base_name}_data.csv"] = csv_bio.getvalue()

    # 3. Synthetic dataset (.xlsx)
    xlsx_bio = BytesIO()
    with pd.ExcelWriter(xlsx_bio, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Synthetic_Data", index=False)
    deliverables[f"{base_name}_data.xlsx"] = xlsx_bio.getvalue()

    # 4. Reproducible Python generation script (.py)
    script_str = generate_reproducible_script(config)
    deliverables["generate_dataset.py"] = script_str.encode("utf-8")

    # 5. Plain-language dataset documentation (.docx)
    doc_docx_bytes = generate_dataset_documentation_docx(config, df, report)
    deliverables[f"{base_name}_documentation.docx"] = doc_docx_bytes

    # 6. Quality validation report (.docx)
    val_docx_bytes = generate_validation_report_docx(config, report)
    deliverables[f"{base_name}_validation_report.docx"] = val_docx_bytes

    # 7. Quality validation report (.pdf)
    val_pdf_bytes = generate_validation_report_pdf(config, report)
    deliverables[f"{base_name}_validation_report.pdf"] = val_pdf_bytes

    # 8. Assumptions and limitations report (.md)
    assumptions_md = generate_assumptions_and_limitations_md(config, report)
    deliverables[f"{base_name}_assumptions_and_limitations.md"] = assumptions_md.encode("utf-8")

    # 9. Generation configuration in JSON (.json)
    deliverables["generation_config.json"] = config.to_json(indent=2).encode("utf-8")

    # 10. Validation results in a machine-readable format (.json)
    val_json_str = json.dumps(report.to_dict(), indent=2)
    deliverables["validation_results.json"] = val_json_str.encode("utf-8")

    # 11. Generation metadata and reproducibility information (.json)
    metadata = {
        "project_name": config.project_name,
        "domain": config.domain,
        "country": config.country,
        "record_count": len(df),
        "column_count": len(df.columns),
        "random_seed": config.random_seed,
        "timestamp": report.timestamp,
        "reproducibility": {
            "python_version": "3.11",
            "numpy_random_generator": "default_rng",
            "seed": config.random_seed,
        },
        "quality_summary": {
            "passed": report.passed,
            "warnings": report.warnings,
            "failures": report.failures,
            "is_approved": report.is_approved,
        },
    }
    deliverables["generation_metadata.json"] = json.dumps(metadata, indent=2).encode("utf-8")

    # 12. Create ZIP archive
    zip_bio = BytesIO()
    with zipfile.ZipFile(zip_bio, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for fname, fbytes in deliverables.items():
            zip_file.writestr(fname, fbytes)

    deliverables[f"{base_name}_deliverables.zip"] = zip_bio.getvalue()

    return deliverables


def save_deliverables_to_disk(
    deliverables: dict[str, bytes],
    target_dir: Path | None = None,
) -> list[Path]:
    """Save all deliverables to disk safely."""
    dest_dir = target_dir or OUTPUT_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for fname, fbytes in deliverables.items():
        # Prevent path traversal
        clean_name = Path(fname).name
        target_path = dest_dir / clean_name
        target_path.write_bytes(fbytes)
        saved_paths.append(target_path)

    return saved_paths
