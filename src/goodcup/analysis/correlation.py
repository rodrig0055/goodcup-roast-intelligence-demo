"""Roast-metric <-> cup-score associations, under ALL the statistical guardrails
in PRD section 6. These guardrails are the core value of the tool, not decoration:
a correlation table without N, CIs and multiple-comparison control produces
confident garbage that gets acted on.

Every row reports: N, effect size (Pearson r) first, a 95% CI (bootstrap when
N<30, else Fisher-z), the raw p AND the Benjamini-Hochberg FDR-adjusted p, and a
small-sample flag. The report also states K (how many variables were scanned --
scanning K inflates false positives), flags confounders (mixed machines / origins /
processes), offers within-stratum views, and marks the whole thing "exploratory
only" below the Phase 2 data gate.

Language here is deliberately neutral; the dashboard renders it as *associated with*,
never *causes*. A correlation on our data is a hypothesis to test on the roaster.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from config import (
    BOOTSTRAP_ITERS,
    BOOTSTRAP_MAX_N,
    MIN_STRATUM_N,
    PHASE2_MIN_MATCHED_ROASTS,
    RANDOM_SEED,
    SMALL_SAMPLE_WARN_N,
)
from goodcup.db import models

#: Roast variables scanned against cup score by default. ``charge_temp`` and the
#: turning-point columns are essentially null in the demo data -- included so the
#: FDR correction can be seen suppressing them.
DEFAULT_METRICS = [
    "dtr_pct",
    "development_time_s",
    "drying_time_s",
    "maillard_time_s",
    "total_time_s",
    "drop_temp",
    "charge_temp",
    "turning_point_temp",
    "turning_point_time_s",
]

METRIC_LABELS = {
    "dtr_pct": "Development Time Ratio (%)",
    "development_time_s": "Development time (s)",
    "drying_time_s": "Drying time (s)",
    "maillard_time_s": "Maillard time (s)",
    "total_time_s": "Total roast time (s)",
    "drop_temp": "Drop temperature",
    "charge_temp": "Charge temperature",
    "turning_point_temp": "Turning-point temp",
    "turning_point_time_s": "Turning-point time (s)",
}

CONFOUNDER_DIMENSIONS = ["machine_id", "process", "origin_country"]


# --------------------------------------------------------------------------- #
# Stats helpers
# --------------------------------------------------------------------------- #
def effect_label(r: float) -> str:
    a = abs(r)
    if a < 0.1:
        return "negligible"
    if a < 0.3:
        return "small"
    if a < 0.5:
        return "moderate"
    return "large"


def _fisher_ci(r: float, n: int, alpha: float = 0.05) -> tuple[float, float]:
    if n < 4 or abs(r) >= 1.0:
        return (float("nan"), float("nan"))
    z = np.arctanh(r)
    se = 1.0 / np.sqrt(n - 3)
    crit = stats.norm.ppf(1 - alpha / 2)
    lo, hi = np.tanh(z - crit * se), np.tanh(z + crit * se)
    return float(lo), float(hi)


def _bootstrap_ci(
    x: np.ndarray, y: np.ndarray, iters: int = BOOTSTRAP_ITERS, alpha: float = 0.05
) -> tuple[float, float]:
    n = len(x)
    if n < 4:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(RANDOM_SEED)
    idx = rng.integers(0, n, size=(iters, n))
    rs = np.empty(iters)
    for i in range(iters):
        xi, yi = x[idx[i]], y[idx[i]]
        if np.std(xi) == 0 or np.std(yi) == 0:
            rs[i] = 0.0
        else:
            rs[i] = np.corrcoef(xi, yi)[0, 1]
    lo, hi = np.nanpercentile(rs, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(lo), float(hi)


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    """BH FDR-adjusted p-values (no external dependency)."""
    p = np.asarray(pvals, dtype=float)
    n = p.size
    if n == 0:
        return []
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.clip(adj, 0.0, 1.0)
    return out.tolist()


# --------------------------------------------------------------------------- #
# Result containers
# --------------------------------------------------------------------------- #
@dataclass
class AssociationTable:
    label: str
    score_col: str
    k: int
    rows: list[dict] = field(default_factory=list)

    def to_frame(self):
        import pandas as pd

        return pd.DataFrame(self.rows)


@dataclass
class CorrelationReport:
    n_matched: int
    exploratory: bool
    gate: int
    confounders: dict
    overall: AssociationTable
    strata: dict[str, list[AssociationTable]]


# --------------------------------------------------------------------------- #
# Core scan
# --------------------------------------------------------------------------- #
def _scan(df, metrics: list[str], score_col: str, label: str) -> AssociationTable:
    present = [m for m in metrics if m in df.columns]
    raw_rows: list[dict] = []
    for m in present:
        sub = df[[m, score_col]].dropna()
        n = len(sub)
        if n < 3 or sub[m].std() == 0 or sub[score_col].std() == 0:
            raw_rows.append({
                "metric": m, "label": METRIC_LABELS.get(m, m), "n": n,
                "r": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"),
                "p_raw": float("nan"), "effect": "n/a",
                "small_sample": n < SMALL_SAMPLE_WARN_N,
            })
            continue
        x = sub[m].to_numpy(float)
        y = sub[score_col].to_numpy(float)
        r, p = stats.pearsonr(x, y)
        if n <= BOOTSTRAP_MAX_N:
            lo, hi = _bootstrap_ci(x, y)
            ci_method = "bootstrap"
        else:
            lo, hi = _fisher_ci(r, n)
            ci_method = "fisher"
        raw_rows.append({
            "metric": m, "label": METRIC_LABELS.get(m, m), "n": n,
            "r": float(r), "ci_low": lo, "ci_high": hi, "ci_method": ci_method,
            "p_raw": float(p), "effect": effect_label(r),
            "small_sample": n < SMALL_SAMPLE_WARN_N,
        })

    # BH FDR across the scanned variables that produced a p-value
    tested = [row for row in raw_rows if not np.isnan(row["p_raw"])]
    adj = benjamini_hochberg([row["p_raw"] for row in tested])
    for row, a in zip(tested, adj):
        row["p_fdr"] = float(a)
    for row in raw_rows:
        row.setdefault("p_fdr", float("nan"))

    # rank by effect size magnitude (guardrail 5: lead with effect size)
    raw_rows.sort(key=lambda d: (-(abs(d["r"]) if not np.isnan(d["r"]) else -1)))
    return AssociationTable(label=label, score_col=score_col, k=len(tested), rows=raw_rows)


def _detect_confounders(df) -> dict:
    out = {}
    for dim in CONFOUNDER_DIMENSIONS:
        if dim in df.columns:
            levels = sorted(x for x in df[dim].dropna().unique())
            if len(levels) > 1:
                out[dim] = levels
    return out


def correlation_report(
    conn,
    score_col: str = "mean_total_score",
    metrics: list[str] | None = None,
    stratify: bool = True,
) -> CorrelationReport:
    """Full guarded correlation report over the matched roasts."""
    metrics = metrics or DEFAULT_METRICS
    df = models.read_sql(conn, "SELECT * FROM matched_roasts")
    n_matched = len(df)
    exploratory = n_matched < PHASE2_MIN_MATCHED_ROASTS
    confounders = _detect_confounders(df)

    overall = _scan(df, metrics, score_col, label="All roasts")

    strata: dict[str, list[AssociationTable]] = {}
    if stratify:
        for dim, levels in confounders.items():
            tables = []
            for lvl in levels:
                sub = df[df[dim] == lvl]
                if len(sub) >= MIN_STRATUM_N:
                    tables.append(_scan(sub, metrics, score_col, label=f"{dim} = {lvl}"))
            if tables:
                strata[dim] = tables

    return CorrelationReport(
        n_matched=n_matched,
        exploratory=exploratory,
        gate=PHASE2_MIN_MATCHED_ROASTS,
        confounders=confounders,
        overall=overall,
        strata=strata,
    )
