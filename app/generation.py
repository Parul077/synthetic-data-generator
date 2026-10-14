import ast
import logging
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from app.schemas import ColumnSpec, GenerationConfig

logger = logging.getLogger("synthetic_data_generator.generation")


class SafeFormulaEvaluator(ast.NodeVisitor):
    """
    Safely evaluate derived variable formulas using AST without python eval().
    Supports column arithmetic, comparisons, conditionals, and standard mathematical operations.
    """

    ALLOWED_OPERATORS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / (b.replace(0, np.nan) if hasattr(b, "replace") else (b if b != 0 else np.nan)),
        ast.Mod: lambda a, b: a % b,
        ast.USub: lambda a: -a,
        ast.UAdd: lambda a: +a,
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
        ast.In: lambda a, b: a.isin(b) if hasattr(a, "isin") else a in b,
    }

    def __init__(self, context: dict[str, Any]):
        self.context = context

    def evaluate(self, expr_str: str) -> Any:
        cleaned = expr_str.strip()
        parsed = ast.parse(cleaned, mode="eval")
        return self.visit(parsed.body)

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left = self.visit(node.left)
        right = self.visit(node.right)
        op_type = type(node.op)
        if op_type not in self.ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported binary operator in formula: {op_type.__name__}")
        return self.ALLOWED_OPERATORS[op_type](left, right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        op_type = type(node.op)
        if op_type not in self.ALLOWED_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return self.ALLOWED_OPERATORS[op_type](operand)

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        result = None
        current_left = left
        for op, comparator_node in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in self.ALLOWED_OPERATORS:
                raise ValueError(f"Unsupported comparison operator: {op_type.__name__}")
            comparator = self.visit(comparator_node)
            sub_res = self.ALLOWED_OPERATORS[op_type](current_left, comparator)
            result = sub_res if result is None else (result & sub_res)
            current_left = comparator
        return result

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [self.visit(val) for val in node.values]
        if isinstance(node.op, ast.And):
            res = values[0]
            for v in values[1:]:
                res = res & v
            return res
        elif isinstance(node.op, ast.Or):
            res = values[0]
            for v in values[1:]:
                res = res | v
            return res
        raise ValueError(f"Unsupported boolean operator: {type(node.op).__name__}")

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        test = self.visit(node.test)
        body = self.visit(node.body)
        orelse = self.visit(node.orelse)
        if isinstance(test, pd.Series):
            return pd.Series(np.where(test, body, orelse), index=test.index)
        return body if test else orelse

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_Name(self, node: ast.Name) -> Any:
        name = node.id
        if name in self.context:
            return self.context[name]
        if name == "True":
            return True
        if name == "False":
            return False
        raise ValueError(f"Variable or column '{name}' referenced in formula is not defined in context.")

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(elt) for elt in node.elts)

    def generic_visit(self, node: ast.AST) -> Any:
        raise ValueError(f"Unsupported syntax construct in formula: {type(node).__name__}")


def evaluate_formula(formula: str, df: pd.DataFrame) -> pd.Series | np.ndarray:
    """Safe evaluation of derived formulas on dataframe columns without eval()."""
    context = {col: df[col] for col in df.columns}
    evaluator = SafeFormulaEvaluator(context)
    result = evaluator.evaluate(formula)
    if not isinstance(result, pd.Series):
        result = pd.Series(result, index=df.index)
    return result


def _generate_correlated_gaussian(
    n: int,
    col_names: list[str],
    correlations: list[dict[str, Any]],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """
    Generate correlated standard uniform variables U in [0, 1] using Gaussian Copula.
    """
    k = len(col_names)
    col_idx = {name: i for i, name in enumerate(col_names)}
    corr_matrix = np.eye(k)

    for corr in correlations:
        c1 = corr.get("col1")
        c2 = corr.get("col2")
        target = float(corr.get("target_corr", 0.0))
        if c1 in col_idx and c2 in col_idx:
            i, j = col_idx[c1], col_idx[c2]
            corr_matrix[i, j] = target
            corr_matrix[j, i] = target

    # Ensure positive semi-definiteness via eigenvalue clipping
    eigvals, eigvecs = np.linalg.eigh(corr_matrix)
    eigvals = np.maximum(eigvals, 1e-6)
    corr_matrix = eigvecs @ np.diag(eigvals) @ eigvecs.T
    d = np.sqrt(np.diag(corr_matrix))
    corr_matrix = corr_matrix / np.outer(d, d)

    try:
        chol = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        chol = np.eye(k)

    z = rng.standard_normal((n, k)) @ chol.T
    u = stats.norm.cdf(z)
    return pd.DataFrame(u, columns=col_names)


def generate_synthetic_dataset(config: GenerationConfig) -> pd.DataFrame:
    """
    Deterministically generate the complete synthetic dataset according to config.
    """
    rng = np.random.default_rng(config.random_seed)
    n = config.record_count

    df = pd.DataFrame(index=range(n))

    # Identify continuous columns with correlation requirements
    corr_cols = set()
    for corr in config.correlations:
        c1 = corr.get("col1")
        c2 = corr.get("col2")
        if c1 and c2:
            corr_cols.add(c1)
            corr_cols.add(c2)

    corr_col_list = sorted(list(corr_cols))
    copula_uniforms: pd.DataFrame | None = None
    if len(corr_col_list) >= 2:
        copula_uniforms = _generate_correlated_gaussian(n, corr_col_list, config.correlations, rng)

    # 1. Generate Independent Base Features
    for col in config.columns:
        if col.is_derived:
            continue

        cname = col.name
        dist = col.distribution.lower()
        p = col.params

        if col.is_id or dist == "id":
            prefix = p.get("prefix", "CUST-")
            digits = int(p.get("digits", 6))
            fmt = f"{prefix}{{:0{digits}d}}"
            df[cname] = [fmt.format(i + 1) for i in range(n)]

        elif col.data_type == "category" or dist == "categorical":
            categories = p.get("categories", ["Cat_A", "Cat_B"])
            weights = p.get("proportions")
            if weights and len(weights) == len(categories):
                weights = np.array(weights, dtype=float)
                weights = weights / weights.sum()
            else:
                weights = None
            df[cname] = rng.choice(categories, size=n, p=weights)

        elif col.data_type == "date" or dist == "date_range":
            start_str = p.get("start_date", "2023-01-01")
            end_str = p.get("end_date", "2024-12-31")
            start_dt = datetime.strptime(start_str, "%Y-%m-%d")
            end_dt = datetime.strptime(end_str, "%Y-%m-%d")
            delta_days = (end_dt - start_dt).days
            if delta_days <= 0:
                delta_days = 365
            random_days = rng.integers(0, delta_days + 1, size=n)
            df[cname] = [start_dt + timedelta(days=int(d)) for d in random_days]

        else:
            # Numeric continuous/discrete distributions
            u = copula_uniforms[cname].values if copula_uniforms is not None and cname in copula_uniforms else None

            if dist == "normal":
                mean = float(p.get("mean", 50.0))
                std = float(p.get("std", 15.0))
                if u is not None:
                    values = stats.norm.ppf(np.clip(u, 1e-5, 1 - 1e-5), loc=mean, scale=std)
                else:
                    values = rng.normal(loc=mean, scale=std, size=n)

            elif dist == "lognormal":
                mean = float(p.get("mean", 100000.0))
                std = float(p.get("std", 60000.0))
                # Parameterize lognormal from target mean and std
                var = std**2
                mu = np.log((mean**2) / np.sqrt(var + mean**2))
                sigma = np.sqrt(np.log(var / (mean**2) + 1))
                if u is not None:
                    values = stats.lognorm.ppf(np.clip(u, 1e-5, 1 - 1e-5), s=sigma, scale=np.exp(mu))
                else:
                    values = rng.lognormal(mean=mu, sigma=sigma, size=n)

            elif dist == "uniform":
                low = float(p.get("min", 0.0))
                high = float(p.get("max", 100.0))
                if u is not None:
                    values = low + u * (high - low)
                else:
                    values = rng.uniform(low=low, high=high, size=n)

            elif dist == "exponential":
                scale = float(p.get("scale", 10.0))
                if u is not None:
                    values = stats.expon.ppf(np.clip(u, 1e-5, 1 - 1e-5), scale=scale)
                else:
                    values = rng.exponential(scale=scale, size=n)

            elif dist == "beta":
                a = float(p.get("a", 2.0))
                b = float(p.get("b", 5.0))
                if u is not None:
                    values = stats.beta.ppf(np.clip(u, 1e-5, 1 - 1e-5), a=a, b=b)
                else:
                    values = rng.beta(a=a, b=b, size=n)

            else:
                # Default fallback normal
                values = rng.normal(loc=50.0, scale=10.0, size=n)

            # Apply hard bounds if specified
            if col.hard_min is not None:
                values = np.maximum(values, col.hard_min)
            if col.hard_max is not None:
                values = np.minimum(values, col.hard_max)

            if col.data_type == "integer":
                values = np.round(values).astype(int)

            df[cname] = values

    # 2. Compute Derived Features (Initial pass before noise)
    for col in config.columns:
        if col.is_derived and col.formula:
            try:
                res = evaluate_formula(col.formula, df)
                if col.data_type == "integer":
                    res = np.round(res).astype(int)
                elif col.data_type == "float":
                    res = res.astype(float)
                if col.hard_min is not None:
                    res = np.maximum(res, col.hard_min)
                if col.hard_max is not None:
                    res = np.minimum(res, col.hard_max)
                df[col.name] = res
            except Exception as exc:
                logger.error("Failed to evaluate initial formula for %s: %s", col.name, exc)
                df[col.name] = 0

    # 3. Apply 15% Noise Policy
    apply_noise_policy(df, config, rng)

    # 4. Recompute Derived Features and Re-enforce Constraints Post-Noise
    for col in config.columns:
        if col.is_derived and col.formula:
            try:
                res = evaluate_formula(col.formula, df)
                if col.data_type == "integer":
                    res = np.round(res).astype(int)
                elif col.data_type == "float":
                    res = res.astype(float)
                if col.hard_min is not None:
                    res = np.maximum(res, col.hard_min)
                if col.hard_max is not None:
                    res = np.minimum(res, col.hard_max)
                df[col.name] = res
            except Exception as exc:
                logger.error("Failed to evaluate post-noise formula for %s: %s", col.name, exc)

    # 5. Apply Configurable Missingness (if specified in column specs)
    for col in config.columns:
        if col.nullable and col.null_percentage > 0:
            null_count = int(n * min(max(col.null_percentage, 0.0), 1.0))
            if null_count > 0:
                null_indices = rng.choice(n, size=null_count, replace=False)
                df.loc[null_indices, col.name] = np.nan

    # 6. Ensure exact column order matching config
    configured_order = [c.name for c in config.columns if c.name in df.columns]
    df = df[configured_order]

    return df


def apply_noise_policy(
    df: pd.DataFrame, config: GenerationConfig, rng: np.random.Generator
) -> dict[str, Any]:
    """
    Explicitly apply noise according to the configured noise policy:
    - 15% of records in eligible continuous feature columns receive bounded perturbation.
    - Zero noise is applied to categories, IDs, dates, derived identities, or hard targets.
    - Hard bounds are enforced immediately after perturbation.
    """
    noise_cfg = config.noise_policy
    target_pct = float(noise_cfg.percentage)  # e.g. 0.15 (15%)
    scale = float(noise_cfg.perturbation_scale)  # e.g. 0.10 relative jitter
    n = len(df)

    # Determine eligible columns
    eligible = [
        c.name
        for c in config.columns
        if c.noise_eligible
        and not c.is_id
        and not c.is_derived
        and not c.is_target
        and c.data_type in ("float", "integer")
        and c.name in df.columns
    ]

    col_spec_map = {c.name: c for c in config.columns}
    noise_metadata: dict[str, Any] = {
        "target_percentage": target_pct,
        "eligible_columns": eligible,
        "records_perturbed": {},
    }

    if not eligible:
        return noise_metadata

    num_perturbed = int(round(n * target_pct))
    for cname in eligible:
        spec = col_spec_map[cname]
        # Deterministically choose exactly 15% of rows
        indices = rng.choice(n, size=num_perturbed, replace=False)
        original_vals = df.loc[indices, cname].to_numpy(dtype=float)

        std_dev = float(df[cname].std())
        if std_dev == 0 or np.isnan(std_dev):
            std_dev = 1.0

        # Controlled Gaussian jitter
        jitter = rng.normal(0, scale * std_dev, size=num_perturbed)
        noisy_vals = original_vals + jitter

        # Enforce bounds
        if spec.hard_min is not None:
            noisy_vals = np.maximum(noisy_vals, spec.hard_min)
        if spec.hard_max is not None:
            noisy_vals = np.minimum(noisy_vals, spec.hard_max)

        if spec.data_type == "integer":
            noisy_vals = np.round(noisy_vals).astype(int)

        df.loc[indices, cname] = noisy_vals
        noise_metadata["records_perturbed"][cname] = num_perturbed

    return noise_metadata


def generate_reproducible_script(config: GenerationConfig) -> str:
    """
    Generate a standalone, self-contained Python script that completely reproduces
    the synthetic dataset generation with the approved configuration and seed.
    """
    cfg_json = config.to_json(indent=4)
    script = f'''"""
Standalone Reproducible Synthetic Data Generation Script
Project: {config.project_name}
Generated by Synthetic Data Generator
Target Record Count: {config.record_count}
Random Seed: {config.random_seed}
"""

import json
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from scipy import stats

CONFIG_JSON = r\'\'\'{cfg_json}\'\'\'

def main():
    config = json.loads(CONFIG_JSON)
    seed = config["random_seed"]
    n = config["record_count"]
    rng = np.random.default_rng(seed)
    
    print(f"Generating {{n}} records with random seed {{seed}}...")
    
    # Import application generator or execute embedded logic
    from app.schemas import GenerationConfig
    from app.generation import generate_synthetic_dataset
    
    cfg = GenerationConfig.from_dict(config)
    df = generate_synthetic_dataset(cfg)
    
    output_filename = "synthetic_dataset.csv"
    df.to_csv(output_filename, index=False)
    print(f"Successfully generated {{len(df)}} records into {{output_filename}}.")

if __name__ == "__main__":
    main()
'''
    return script
