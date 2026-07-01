"""Tests for confounder-adjusted (partial) association."""

from __future__ import annotations

import numpy as np
import pandas as pd

from goodcup.analysis.correlation import partial_association


def test_partial_correlation_shrinks_a_confounded_association():
    # score is driven purely by machine; dtr differs by machine too but has no
    # own effect -> a strong SIMPLE r that should collapse once machine is held.
    rng = np.random.default_rng(0)
    rows = []
    for machine, base_dtr, base_score in [("M1", 15.0, 82.0), ("M2", 21.0, 87.0)]:
        for _ in range(30):
            rows.append({
                "machine_id": machine,
                "dtr_pct": base_dtr + rng.normal(0, 0.3),
                "mean_total_score": base_score + rng.normal(0, 0.3),
                "process": "washed", "origin_country": "Ethiopia",
            })
    df = pd.DataFrame(rows)
    res = partial_association(df, "dtr_pct", covariates=["machine_id"])
    assert abs(res["simple_r"]) > 0.8            # strong confounded association
    assert abs(res["partial_r"]) < 0.4           # collapses once machine held constant
    assert res["k_covariates"] == 1


def test_partial_correlation_preserves_a_genuine_within_group_effect():
    # dtr genuinely raises score WITHIN each machine -> partial r stays strong.
    rng = np.random.default_rng(1)
    rows = []
    for machine, offset in [("M1", 0.0), ("M2", 3.0)]:
        for _ in range(30):
            dtr = rng.uniform(15, 22)
            rows.append({
                "machine_id": machine, "dtr_pct": dtr,
                "mean_total_score": 80 + offset + 0.6 * dtr + rng.normal(0, 0.4),
                "process": "washed", "origin_country": "Ethiopia",
            })
    df = pd.DataFrame(rows)
    res = partial_association(df, "dtr_pct", covariates=["machine_id"])
    assert res["partial_r"] > 0.6
    assert res["ci_low"] > 0                     # CI excludes zero
    assert res["p"] < 0.05


def test_partial_association_degrades_gracefully_without_covariates():
    df = pd.DataFrame({"dtr_pct": [15, 16, 17, 18, 19, 20], "mean_total_score": [82, 83, 84, 85, 86, 87]})
    res = partial_association(df, "dtr_pct", covariates=[])
    assert res["k_covariates"] == 0
    # with nothing to adjust for, partial == simple
    assert res["partial_r"] == res["simple_r"]
