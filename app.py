import io
import json
import logging
import warnings
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

# Filter benign UserWarning from openpyxl
warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

from app.claude_client import (
    propose_generation_config,
    propose_specification,
    test_connection,
)
from app.config import (
    ANTHROPIC_MODEL,
    CLAUDE_MOCK_MODE,
    DOMAIN_PRESETS,
    get_mock_mode,
    validate_config,
)
from app.export import build_all_deliverables, sanitize_filename
from app.generation import generate_synthetic_dataset
from app.schemas import GenerationConfig, SpecificationSuggestion
from app.specification import (
    convert_specification_to_config,
    validate_specification_items,
)
from app.validation import repair_dataset, validate_dataset
from app.workbook import (
    apply_approved_specification,
    create_project_template_workbook,
    create_sample_investment_workbook,
    inspect_workbook,
)

# Page configuration
st.set_page_config(
    page_title="Synthetic Data Generator",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("synthetic_data_generator.ui")

# Initialize Project Definition Widget State Keys
if "input_project_name" not in st.session_state:
    st.session_state.input_project_name = ""
if "input_domain" not in st.session_state:
    st.session_state.input_domain = ""
if "input_country" not in st.session_state:
    st.session_state.input_country = ""
if "input_dataset_objective" not in st.session_state:
    st.session_state.input_dataset_objective = ""
if "input_data_structure" not in st.session_state:
    st.session_state.input_data_structure = "Tabular"
if "input_record_count" not in st.session_state:
    st.session_state.input_record_count = 10000
if "input_random_seed" not in st.session_state:
    st.session_state.input_random_seed = 42
if "input_additional_requirements" not in st.session_state:
    st.session_state.input_additional_requirements = ""
if "preset_choice" not in st.session_state:
    st.session_state.preset_choice = "Custom / Blank Project"


def sync_project_metadata() -> None:
    """Keep st.session_state.project_metadata synchronized with current widget input keys."""
    raw_name = str(st.session_state.get("input_project_name", "")).strip()
    raw_domain = str(st.session_state.get("input_domain", "")).strip()
    raw_country = str(st.session_state.get("input_country", "")).strip()
    raw_obj = str(st.session_state.get("input_dataset_objective", "")).strip()
    raw_struct = str(st.session_state.get("input_data_structure", "Tabular")).strip().lower()
    raw_addl = str(st.session_state.get("input_additional_requirements", "")).strip()

    st.session_state.project_metadata = {
        "project_name": raw_name or "Custom Synthetic Dataset",
        "domain": raw_domain or "General Industry",
        "country": raw_country or "Global",
        "dataset_objective": raw_obj or "Generate representative synthetic observations.",
        "data_structure": raw_struct if raw_struct in ["tabular", "longitudinal", "time series"] else "tabular",
        "record_count": int(st.session_state.get("input_record_count", 10000)),
        "random_seed": int(st.session_state.get("input_random_seed", 42)),
        "additional_requirements": raw_addl,
    }


def on_preset_change() -> None:
    """Callback when user selects a preset dropdown option: populates fields or clears for Custom/Blank."""
    chosen = st.session_state.preset_choice
    preset = DOMAIN_PRESETS.get(chosen, DOMAIN_PRESETS["Custom / Blank Project"])
    st.session_state.input_project_name = preset.get("project_name", "")
    st.session_state.input_domain = preset.get("domain", "")
    st.session_state.input_country = preset.get("country", "")
    st.session_state.input_dataset_objective = preset.get("dataset_objective", "")
    struct = preset.get("data_structure", "tabular").capitalize()
    st.session_state.input_data_structure = struct if struct in ["Tabular", "Longitudinal", "Time Series"] else "Tabular"
    st.session_state.input_record_count = int(preset.get("record_count", 10000))
    st.session_state.input_random_seed = int(preset.get("random_seed", 42))
    st.session_state.input_additional_requirements = preset.get("additional_requirements", "")
    sync_project_metadata()


# Initialize Session State
if "project_metadata" not in st.session_state:
    sync_project_metadata()
if "workbook_bytes" not in st.session_state:
    st.session_state.workbook_bytes = None
if "workbook_name" not in st.session_state:
    st.session_state.workbook_name = ""
if "workbook_metadata" not in st.session_state:
    st.session_state.workbook_metadata = None
if "spec_suggestions" not in st.session_state:
    st.session_state.spec_suggestions = []
if "spec_approved" not in st.session_state:
    st.session_state.spec_approved = False
if "completed_workbook_bytes" not in st.session_state:
    st.session_state.completed_workbook_bytes = None
if "generation_config" not in st.session_state:
    st.session_state.generation_config = None
if "synthetic_df" not in st.session_state:
    st.session_state.synthetic_df = None
if "validation_report" not in st.session_state:
    st.session_state.validation_report = None
if "deliverables" not in st.session_state:
    st.session_state.deliverables = {}


# --- Sidebar ---
with st.sidebar:
    st.title("⚙️ System Status")
    mock_active = get_mock_mode()
    if mock_active:
        st.info("🟡 **Mode: Mock (Offline)**\nNo Anthropic API key required. Domain-aware simulation enabled.")
    else:
        st.success(f"🟢 **Mode: Live API**\nTarget model: `{ANTHROPIC_MODEL}`")

    st.divider()
    st.subheader("Claude Connectivity")
    if st.button("Test Claude API Connection", use_container_width=True):
        with st.spinner("Checking API status..."):
            try:
                res = test_connection()
                st.success("API check succeeded.")
                st.code(res, language="json")
            except Exception as exc:
                st.error(f"API Error: {exc}")

    st.divider()
    st.subheader("Specification Template")
    st.caption("Generate or download an Excel specification template matching your current project definition.")

    if st.button("Generate Template for Current Project", use_container_width=True):
        tmpl_bytes = create_project_template_workbook(st.session_state.project_metadata)
        st.session_state.workbook_bytes = tmpl_bytes
        st.session_state.workbook_name = f"{sanitize_filename(st.session_state.project_metadata['project_name'])}_template.xlsx"
        st.session_state.workbook_metadata = inspect_workbook(tmpl_bytes)
        st.session_state.spec_approved = False
        st.session_state.spec_suggestions = []
        st.success(f"Generated template for domain '{st.session_state.project_metadata['domain']}'!")
        st.rerun()

    current_tmpl_bytes = create_project_template_workbook(st.session_state.project_metadata)
    st.download_button(
        label="Download Blank Template (.xlsx)",
        data=current_tmpl_bytes,
        file_name=f"{sanitize_filename(st.session_state.project_metadata['project_name'])}_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.divider()
    st.caption(f"**Current Domain:** {st.session_state.project_metadata.get('domain', 'General')}")
    st.caption(f"**Records:** {st.session_state.project_metadata.get('record_count', 10000):,}")
    st.caption(f"**Seed:** {st.session_state.project_metadata.get('random_seed', 42)}")

    if st.button("Reset Session State", use_container_width=True):
        st.session_state.clear()
        st.rerun()


# --- Main Title ---
st.title("📊 Synthetic Data Generator")
st.caption(
    "A generic, domain-agnostic platform automating the workflow from Excel specification to "
    "reproducible synthetic data generation, quality validation, and deliverables."
)

# Workflow Tabs
tab_a, tab_b, tab_c, tab_de, tab_f, tab_g = st.tabs([
    "Stage A: Project & Setup",
    "Stage B: Specification Builder",
    "Stage C: Approval & Workbook",
    "Stage D & E: Data Generation",
    "Stage F: Quality Validation",
    "Stage G: Export & Deliverables",
])


# ==========================================
# STAGE A: Project Creation & Setup
# ==========================================
with tab_a:
    st.header("Stage A: Project Creation & Template Inspection")

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("1. Project Definition")

        # Optional Preset Selector with on_change callback
        preset_names = list(DOMAIN_PRESETS.keys())
        st.selectbox(
            "Quick-Start Preset (Optional)",
            preset_names,
            key="preset_choice",
            on_change=on_preset_change,
            help="Select a starter template to pre-populate fields, or choose Custom / Blank Project to clear preset defaults and define any custom domain.",
        )

        st.text_input(
            "Project Name",
            key="input_project_name",
            on_change=sync_project_metadata,
            placeholder="e.g., Renewable Energy Grid Telemetry, Clinical Patient Cohort, Retail E-Commerce",
            help="Enter a descriptive project name for any domain or dataset.",
        )
        st.text_input(
            "Domain / Industry",
            key="input_domain",
            on_change=sync_project_metadata,
            placeholder="e.g., Healthcare, Agriculture, Retail, Manufacturing, Energy, Financial Services",
            help="Any industry: Healthcare, Agriculture, Retail, Manufacturing, Financial Services, Education, etc.",
        )
        st.text_input(
            "Country / Jurisdiction",
            key="input_country",
            on_change=sync_project_metadata,
            placeholder="e.g., Germany, Kenya, United Kingdom, United States, Global",
            help="Applicable country or regulatory jurisdiction.",
        )

        st.text_area(
            "Dataset Objective",
            key="input_dataset_objective",
            on_change=sync_project_metadata,
            height=80,
            placeholder="Describe the intended purpose or machine learning objective for this synthetic dataset...",
            help="Describe the intended purpose or machine learning objective for this synthetic dataset.",
        )

        col_a1, col_a2, col_a3 = st.columns(3)
        with col_a1:
            st.selectbox(
                "Data Structure",
                ["Tabular", "Longitudinal", "Time Series"],
                key="input_data_structure",
                on_change=sync_project_metadata,
            )
        with col_a2:
            st.number_input(
                "Record Count",
                min_value=10,
                max_value=500000,
                step=1000,
                key="input_record_count",
                on_change=sync_project_metadata,
            )
        with col_a3:
            st.number_input(
                "Random Seed",
                min_value=0,
                max_value=9999999,
                key="input_random_seed",
                on_change=sync_project_metadata,
            )

        st.text_area(
            "Additional Requirements & Business Rules (Optional)",
            key="input_additional_requirements",
            on_change=sync_project_metadata,
            height=80,
            placeholder="e.g., Specific accounting identities, hard boundaries, mandatory columns, target variable conditions...",
            help="Any custom rules or constraints to guide specification interpretation and generation.",
        )

        # Ensure project metadata is synchronized for this execution
        sync_project_metadata()

    with col2:
        st.subheader("2. Specification Workbook")
        uploaded = st.file_uploader(
            "Upload Excel Specification Workbook (.xlsx)",
            type=["xlsx"],
            key="file_uploader",
            help="Upload an existing specification workbook, or use the sidebar button to generate a template matching your project.",
        )

        if uploaded is not None:
            uploaded_bytes = uploaded.getvalue()
            st.session_state.workbook_bytes = uploaded_bytes
            st.session_state.workbook_name = uploaded.name
            st.session_state.workbook_metadata = inspect_workbook(uploaded_bytes)

        if st.session_state.workbook_bytes:
            st.success(f"Workbook loaded: **{st.session_state.workbook_name or 'Generated Template'}**")
            meta = st.session_state.workbook_metadata
            st.write(f"Worksheets ({meta['sheet_count']}):", ", ".join(meta["sheet_names"]))

            with st.expander("Inspect Sheet Structures & Populated Cells"):
                for sheet in meta["sheets"]:
                    st.markdown(f"**Worksheet: `{sheet['name']}`**")
                    st.write(f"- Dimensions: {sheet['max_row']} rows × {sheet['max_column']} cols")
                    st.write(f"- Merged cells: {len(sheet['merged_cells'])}")
                    st.write(f"- Formulas detected: {len(sheet['formulas'])}")
                    st.write(f"- Populated cells count: {len(sheet['populated_cells'])}")
                    if sheet["formulas"]:
                        st.caption("Formulas:")
                        st.json(sheet["formulas"])
        else:
            st.info(
                "💡 No specification workbook loaded yet. You can upload an `.xlsx` file, "
                "or click **'Generate Template for Current Project'** in the sidebar to create one instantly."
            )

    if st.session_state.workbook_bytes:
        st.markdown("---")
        st.success(
            "✅ **Stage A Complete!** Your project definition and workbook are loaded.\n\n"
            "👉 **Next Step:** Click the **Stage B: Specification Builder** tab at the top of your screen to generate and review AI specification suggestions."
        )


# ==========================================
# STAGE B: AI-Assisted Specification Builder
# ==========================================
with tab_b:
    st.header("Stage B: AI-Assisted Specification Builder")

    if not st.session_state.workbook_bytes or not st.session_state.workbook_metadata:
        st.warning("Please upload or generate a specification workbook in Stage A first.")
    else:
        st.write(
            f"Claude interprets your **{st.session_state.project_metadata.get('domain', 'custom')}** requirements "
            f"and proposes domain-aligned specifications for blank candidate cells."
        )

        col_b1, col_b2 = st.columns([1, 1])
        with col_b1:
            if st.button("Generate Specification Suggestions", type="primary", use_container_width=True):
                with st.spinner("Analyzing workbook and generating domain-adapted proposals..."):
                    try:
                        suggestions = propose_specification(
                            st.session_state.workbook_metadata,
                            st.session_state.project_metadata,
                        )
                        for s in suggestions:
                            s["approved"] = True
                        st.session_state.spec_suggestions = suggestions
                        st.success(f"Generated {len(suggestions)} structured specification suggestions for {st.session_state.project_metadata['domain']}.")
                    except Exception as exc:
                        st.error(f"Failed to generate suggestions: {exc}")

        with col_b2:
            if st.session_state.spec_suggestions:
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("Approve All Suggestions", use_container_width=True):
                        for s in st.session_state.spec_suggestions:
                            s["approved"] = True
                        st.rerun()
                with col_btn2:
                    if st.button("Reject All", use_container_width=True):
                        for s in st.session_state.spec_suggestions:
                            s["approved"] = False
                        st.rerun()

        # Display suggestions
        if st.session_state.spec_suggestions:
            st.subheader("Review & Edit Proposed Specification Values")
            st.caption("Review each proposal, verify assumptions, edit values if needed, and confirm approval.")

            for idx, item in enumerate(st.session_state.spec_suggestions):
                with st.expander(
                    f"[{'APPROVED' if item.get('approved') else 'PENDING'}] {item.get('sheet_name')} - Cell {item.get('cell')}: {item.get('field_name')}",
                    expanded=(idx < 3),
                ):
                    c_edit1, c_edit2 = st.columns([2, 1])
                    with c_edit1:
                        new_val = st.text_input(
                            f"Value for {item.get('cell')}",
                            value=str(item.get("proposed_value", "")),
                            key=f"val_{idx}",
                        )
                        item["proposed_value"] = new_val
                        st.write(f"**Reasoning:** {item.get('reasoning')}")
                        st.write(f"**Assumptions:** {item.get('assumptions')}")
                    with c_edit2:
                        item["approved"] = st.checkbox(
                            "Approve this item",
                            value=bool(item.get("approved", True)),
                            key=f"app_{idx}",
                        )
                        st.write(f"**Confidence:** `{item.get('confidence', 'HIGH')}`")
                        st.write(f"**Source:** {item.get('source', 'AI Inference')}")
                        if item.get("needs_human_confirmation"):
                            st.warning("⚠️ Human confirmation advised.")

        # Manual Fallback Form
        st.divider()
        with st.expander("➕ Manual Entry Fallback (Add Custom Specification Item)"):
            with st.form("manual_spec_form"):
                m_sheet = st.selectbox(
                    "Target Sheet",
                    st.session_state.workbook_metadata["sheet_names"],
                )
                m_cell = st.text_input("Cell Coordinate (e.g. B12)", value="B12")
                m_name = st.text_input("Field Label / Name", value="Custom Rule")
                m_val = st.text_input("Value to Enter", value="Custom Value")
                m_reason = st.text_input("Reasoning / Description", value="Manual entry by user")
                submitted = st.form_submit_button("Add Specification Entry")
                if submitted:
                    st.session_state.spec_suggestions.append({
                        "sheet_name": m_sheet,
                        "cell": m_cell.upper().strip(),
                        "field_name": m_name,
                        "proposed_value": m_val,
                        "reasoning": m_reason,
                        "assumptions": "Manual user entry",
                        "confidence": "HIGH",
                        "source": "Manual User Fallback",
                        "needs_human_confirmation": False,
                        "approved": True,
                    })
                    st.success(f"Added item {m_cell} to specifications.")
                    st.rerun()

        if st.session_state.spec_suggestions:
            st.markdown("---")
            st.info(
                "👉 **Next Step:** Review the suggestions above, ensure desired items are marked **Approved**, then click the **Stage C: Approval & Workbook** tab at the top to validate and finalize your workbook."
            )


# ==========================================
# STAGE C: Specification Approval
# ==========================================
with tab_c:
    st.header("Stage C: Specification Validation & Approval")

    if not st.session_state.spec_suggestions:
        st.warning("Please generate or enter specification items in Stage B first.")
    else:
        approved_items = [s for s in st.session_state.spec_suggestions if s.get("approved")]
        st.write(f"Approved Items: **{len(approved_items)}** / {len(st.session_state.spec_suggestions)} total items.")

        # Validate specifications before approval
        errors = validate_specification_items(approved_items, st.session_state.workbook_metadata)

        if errors:
            st.error("Validation issues detected in specification items:")
            for err in errors:
                st.write(f"- ❌ {err}")
            st.session_state.spec_approved = False
        else:
            st.success("All approved specification items passed pre-generation validation checks.")

            if st.button("Finalize & Approve Specification Workbook", type="primary", use_container_width=True):
                with st.spinner("Applying approved values into a separate copy of the workbook..."):
                    try:
                        completed_bytes = apply_approved_specification(
                            st.session_state.workbook_bytes,
                            approved_items,
                        )
                        st.session_state.completed_workbook_bytes = completed_bytes
                        st.session_state.spec_approved = True

                        # Build domain-tailored GenerationConfig
                        st.session_state.generation_config = convert_specification_to_config(
                            approved_items,
                            st.session_state.project_metadata,
                        )
                        st.success("Specification approved! Completed workbook generated.")
                    except Exception as exc:
                        st.error(f"Approval failed: {exc}")

        if st.session_state.completed_workbook_bytes:
            st.download_button(
                label="📥 Download Completed Specification Workbook (.xlsx)",
                data=st.session_state.completed_workbook_bytes,
                file_name=f"{sanitize_filename(st.session_state.project_metadata['project_name'])}_specification.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            st.markdown("---")
            st.info(
                "👉 **Next Step:** Specification approved and workbook generated! Click the **Stage D & E: Data Generation** tab at the top to generate synthetic data with Python."
            )


# ==========================================
# STAGES D & E: Generation Engine
# ==========================================
with tab_de:
    st.header("Stages D & E: Synthetic Data Generation")

    if not st.session_state.spec_approved:
        st.warning("Please complete and approve the specification in Stage C before generating data.")
    else:
        config: GenerationConfig = st.session_state.generation_config

        st.subheader("1. Internal Generation Configuration")
        st.caption(f"Domain: **{config.domain}** | Project: **{config.project_name}** | Target Rows: **{config.record_count:,}**")

        with st.expander("View Strong Schema Configuration (JSON)", expanded=False):
            st.json(config.to_dict())

        st.markdown(
            f"**Records:** {config.record_count:,} | **Columns:** {len(config.columns)} | "
            f"**Random Seed:** {config.random_seed} | **Noise Policy:** {config.noise_policy.percentage:.0%} on eligible features"
        )

        col_g1, col_g2 = st.columns([1, 1])
        with col_g1:
            if st.button("Generate Synthetic Dataset", type="primary", use_container_width=True):
                prog = st.progress(0, text="Initializing generation...")
                try:
                    prog.progress(25, text="Sampling base features and copula distributions...")
                    df = generate_synthetic_dataset(config)
                    prog.progress(70, text="Applying noise policy and enforcing accounting identities...")
                    st.session_state.synthetic_df = df
                    prog.progress(100, text="Generation complete!")
                    st.success(f"Generated {len(df):,} synthetic records with {len(df.columns)} columns for {config.domain}.")
                except Exception as exc:
                    st.error(f"Generation error: {exc}")

        if st.session_state.synthetic_df is not None:
            df = st.session_state.synthetic_df
            st.subheader("2. Dataset Preview & Summary")
            st.dataframe(df.head(25), width="stretch")

            with st.expander("Descriptive Statistics"):
                numeric_cols = df.select_dtypes(include=[np.number])
                if not numeric_cols.empty:
                    st.caption("**Numerical Features Summary**")
                    st.dataframe(numeric_cols.describe().round(4), width="stretch")
                cat_cols = df.select_dtypes(exclude=[np.number])
                if not cat_cols.empty:
                    st.caption("**Categorical & Identifier Features Summary**")
                    st.dataframe(cat_cols.describe().astype(str), width="stretch")

            st.markdown("---")
            st.info(
                "👉 **Next Step:** Synthetic dataset generated! Click the **Stage F: Quality Validation** tab at the top to run automated quality and noise checks."
            )


# ==========================================
# STAGE F: Quality Validation
# ==========================================
with tab_f:
    st.header("Stage F: Quality Validation Engine")

    if st.session_state.synthetic_df is None or st.session_state.generation_config is None:
        st.warning("Please generate a synthetic dataset in Stages D & E first.")
    else:
        config = st.session_state.generation_config
        df = st.session_state.synthetic_df

        col_v1, col_v2 = st.columns([1, 1])
        with col_v1:
            if st.button("Execute Data Quality Validation Checks", type="primary", use_container_width=True):
                with st.spinner("Executing statistical integrity and business rule checks..."):
                    report = validate_dataset(df, config)
                    st.session_state.validation_report = report

        if st.session_state.validation_report is not None:
            report = st.session_state.validation_report

            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("Total Checks", report.total_checks)
            kpi2.metric("Passed", report.passed)
            kpi3.metric("Warnings", report.warnings)
            kpi4.metric("Failures", report.failures)

            if report.failures > 0:
                st.error(f"⚠️ {report.failures} critical check(s) failed.")
                with col_v2:
                    if st.button("Run Bounded Automated Repair", use_container_width=True):
                        with st.spinner("Applying repairs (range clipping, formula re-computation)..."):
                            repaired_df, new_report = repair_dataset(df, config, report)
                            st.session_state.synthetic_df = repaired_df
                            st.session_state.validation_report = new_report
                            st.rerun()
            else:
                st.success("All executed quality checks passed successfully!")

            st.subheader("Detailed Validation Traceability Table")
            val_rows = [i.to_dict() for i in report.items]
            val_df = pd.DataFrame(val_rows)
            st.dataframe(val_df, width="stretch")

            st.markdown("---")
            st.info(
                "👉 **Next Step:** Validation checks completed! Click the **Stage G: Export & Deliverables** tab at the top to download your complete ZIP package (dataset, documentation, reproducible Python code, and quality reports)."
            )


# ==========================================
# STAGE G: Documentation and Export
# ==========================================
with tab_g:
    st.header("Stage G: Documentation & Deliverables Export")

    if (
        st.session_state.synthetic_df is None
        or st.session_state.generation_config is None
        or st.session_state.validation_report is None
    ):
        st.warning("Please complete Generation (Stages D&E) and Validation (Stage F) before exporting deliverables.")
    else:
        config = st.session_state.generation_config
        df = st.session_state.synthetic_df
        report = st.session_state.validation_report
        spec_bytes = st.session_state.completed_workbook_bytes or st.session_state.workbook_bytes

        if not st.session_state.deliverables:
            with st.spinner("Generating deliverables (DOCX, PDF, CSV, XLSX, JSON, ZIP)..."):
                delivs = build_all_deliverables(config, df, report, spec_bytes)
                st.session_state.deliverables = delivs

        delivs = st.session_state.deliverables
        base_name = sanitize_filename(config.project_name)

        zip_key = f"{base_name}_deliverables.zip"
        if zip_key in delivs:
            st.subheader("📦 All-in-One Deliverables Package")
            st.download_button(
                label="📥 Download Complete Deliverables ZIP Archive",
                data=delivs[zip_key],
                file_name=zip_key,
                mime="application/zip",
                type="primary",
                use_container_width=True,
            )

        st.divider()
        st.subheader("Individual Deliverables")

        d_col1, d_col2 = st.columns(2)

        items_list = list(delivs.items())
        half = len(items_list) // 2

        with d_col1:
            for fname, fbytes in items_list[:half]:
                if fname.endswith(".zip"):
                    continue
                st.download_button(
                    label=f"📄 {fname}",
                    data=fbytes,
                    file_name=fname,
                    key=f"dl_{fname}",
                    use_container_width=True,
                )

        with d_col2:
            for fname, fbytes in items_list[half:]:
                if fname.endswith(".zip"):
                    continue
                st.download_button(
                    label=f"📄 {fname}",
                    data=fbytes,
                    file_name=fname,
                    key=f"dl_{fname}",
                    use_container_width=True,
                )
