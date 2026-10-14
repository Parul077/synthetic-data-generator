from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SpecificationSuggestion:
    """An AI-proposed or manual specification entry for a workbook cell/field."""
    sheet_name: str
    cell: str
    field_name: str
    proposed_value: Any
    reasoning: str = ""
    assumptions: str = ""
    confidence: str = "HIGH"  # HIGH, MEDIUM, LOW
    source: str = "AI Inference"
    needs_human_confirmation: bool = False
    approved: bool = False
    status: str = "PROPOSED"  # PROPOSED, APPROVED, REJECTED, MODIFIED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SpecificationSuggestion:
        return cls(
            sheet_name=str(data.get("sheet_name", "Specification")),
            cell=str(data.get("cell", "")).upper().strip(),
            field_name=str(data.get("field_name", "")),
            proposed_value=data.get("proposed_value"),
            reasoning=str(data.get("reasoning", "")),
            assumptions=str(data.get("assumptions", "")),
            confidence=str(data.get("confidence", "HIGH")),
            source=str(data.get("source", "AI Inference")),
            needs_human_confirmation=bool(data.get("needs_human_confirmation", False)),
            approved=bool(data.get("approved", False)),
            status=str(data.get("status", "PROPOSED")),
        )


@dataclass
class ColumnSpec:
    """Specification of a single column for synthetic data generation."""
    name: str
    data_type: str  # integer, float, string, category, date, boolean
    description: str = ""
    distribution: str = "uniform"  # uniform, normal, lognormal, beta, gamma, exponential, categorical, id, date_range
    params: dict[str, Any] = field(default_factory=dict)
    is_id: bool = False
    is_target: bool = False
    is_derived: bool = False
    formula: str = ""
    nullable: bool = False
    null_percentage: float = 0.0
    noise_eligible: bool = True
    hard_min: float | None = None
    hard_max: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColumnSpec:
        return cls(
            name=str(data["name"]),
            data_type=str(data.get("data_type", "float")),
            description=str(data.get("description", "")),
            distribution=str(data.get("distribution", "uniform")),
            params=dict(data.get("params", {})),
            is_id=bool(data.get("is_id", False)),
            is_target=bool(data.get("is_target", False)),
            is_derived=bool(data.get("is_derived", False)),
            formula=str(data.get("formula", "")),
            nullable=bool(data.get("nullable", False)),
            null_percentage=float(data.get("null_percentage", 0.0)),
            noise_eligible=bool(data.get("noise_eligible", not bool(data.get("is_id", False)))),
            hard_min=float(data["hard_min"]) if data.get("hard_min") is not None else None,
            hard_max=float(data["hard_max"]) if data.get("hard_max") is not None else None,
        )


@dataclass
class ConstraintSpec:
    """A business constraint or identity rule."""
    name: str
    type: str  # identity, range, non_negative, sum_equals, inequality, cross_column
    columns: list[str] = field(default_factory=list)
    expression: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConstraintSpec:
        return cls(
            name=str(data.get("name", "Unnamed Constraint")),
            type=str(data.get("type", "identity")),
            columns=list(data.get("columns", [])),
            expression=str(data.get("expression", "")),
            description=str(data.get("description", "")),
        )


@dataclass
class NoisePolicyConfig:
    """Explicit configuration for synthetic data noise addition."""
    percentage: float = 0.15  # 15% noise requirement
    strategy: str = "gaussian_perturbation"
    perturbation_scale: float = 0.10
    eligible_columns: list[str] = field(default_factory=list)
    excluded_columns: list[str] = field(default_factory=list)
    description: str = (
        "15% of records in eligible continuous feature columns receive bounded perturbation. "
        "Categorical, IDs, dates, derived identities, and hard bounds are strictly protected."
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NoisePolicyConfig:
        return cls(
            percentage=float(data.get("percentage", 0.15)),
            strategy=str(data.get("strategy", "gaussian_perturbation")),
            perturbation_scale=float(data.get("perturbation_scale", 0.10)),
            eligible_columns=list(data.get("eligible_columns", [])),
            excluded_columns=list(data.get("excluded_columns", [])),
            description=str(data.get("description", "")),
        )


@dataclass
class GenerationConfig:
    """Complete, self-contained dataset generation configuration."""
    project_name: str
    domain: str
    country: str
    dataset_objective: str
    data_structure: str = "tabular"  # tabular, longitudinal, time_series
    record_count: int = 10000
    random_seed: int = 42
    columns: list[ColumnSpec] = field(default_factory=list)
    constraints: list[ConstraintSpec] = field(default_factory=list)
    correlations: list[dict[str, Any]] = field(default_factory=list)
    noise_policy: NoisePolicyConfig = field(default_factory=NoisePolicyConfig)
    longitudinal_periods: int = 1
    customer_id_col: str = "customer_id"
    time_col: str = "period"
    output_formats: list[str] = field(default_factory=lambda: ["csv", "xlsx", "json"])
    validation_tolerances: dict[str, float] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        return res

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GenerationConfig:
        cols = [ColumnSpec.from_dict(c) for c in data.get("columns", [])]
        constraints = [ConstraintSpec.from_dict(c) for c in data.get("constraints", [])]
        noise = NoisePolicyConfig.from_dict(data.get("noise_policy", {}))
        return cls(
            project_name=str(data.get("project_name", "Synthetic Dataset")),
            domain=str(data.get("domain", "Finance")),
            country=str(data.get("country", "India")),
            dataset_objective=str(data.get("dataset_objective", "")),
            data_structure=str(data.get("data_structure", "tabular")),
            record_count=int(data.get("record_count", 10000)),
            random_seed=int(data.get("random_seed", 42)),
            columns=cols,
            constraints=constraints,
            correlations=list(data.get("correlations", [])),
            noise_policy=noise,
            longitudinal_periods=int(data.get("longitudinal_periods", 1)),
            customer_id_col=str(data.get("customer_id_col", "customer_id")),
            time_col=str(data.get("time_col", "period")),
            output_formats=list(data.get("output_formats", ["csv", "xlsx"])),
            validation_tolerances=dict(data.get("validation_tolerances", {})),
            assumptions=list(data.get("assumptions", [])),
        )

    def validate(self) -> list[str]:
        """Validate internal consistency of the configuration."""
        errors: list[str] = []
        if self.record_count <= 0:
            errors.append(f"Record count must be positive, got {self.record_count}.")
        if not self.columns:
            errors.append("Configuration must define at least one column.")

        col_names = [c.name for c in self.columns]
        if len(col_names) != len(set(col_names)):
            errors.append("Duplicate column names detected.")

        for c in self.columns:
            if c.hard_min is not None and c.hard_max is not None and c.hard_min > c.hard_max:
                errors.append(f"Column '{c.name}': hard_min ({c.hard_min}) > hard_max ({c.hard_max}).")
            if c.is_derived and not c.formula:
                errors.append(f"Derived column '{c.name}' missing formula.")
            if c.null_percentage < 0.0 or c.null_percentage > 1.0:
                errors.append(f"Column '{c.name}': null_percentage must be between 0.0 and 1.0.")

        for corr in self.correlations:
            c1 = corr.get("col1")
            c2 = corr.get("col2")
            if c1 not in col_names or c2 not in col_names:
                errors.append(f"Correlation specified for unknown columns: {c1}, {c2}.")

        return errors


@dataclass
class ValidationResultItem:
    """Single executed quality validation check result."""
    check: str
    requirement: str
    actual_result: str
    status: str  # PASS, WARNING, FAIL, NOT TESTED
    explanation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class ValidationReport:
    """Consolidated validation report with traceability."""
    project_name: str
    timestamp: str
    iteration: int = 1
    total_checks: int = 0
    passed: int = 0
    warnings: int = 0
    failures: int = 0
    not_tested: int = 0
    items: list[ValidationResultItem] = field(default_factory=list)
    is_approved: bool = False
    repair_attempted: bool = False
    unresolved_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "timestamp": self.timestamp,
            "iteration": self.iteration,
            "total_checks": self.total_checks,
            "passed": self.passed,
            "warnings": self.warnings,
            "failures": self.failures,
            "not_tested": self.not_tested,
            "is_approved": self.is_approved,
            "repair_attempted": self.repair_attempted,
            "unresolved_issues": self.unresolved_issues,
            "items": [item.to_dict() for item in self.items],
        }
