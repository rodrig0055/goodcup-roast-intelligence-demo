"""Cupper calibration summaries for coffees scored together in one session."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from config import CALIBRATION_DRIFT_THRESHOLD, SMALL_SAMPLE_WARN_N
from goodcup.db import models


def calibration_report(conn) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return cupper-level status and observation-level deviations."""
    df = models.read_sql(
        conn,
        """
        SELECT cupping_id, roast_id, session_id, cupping_date, cupper_name,
               form_type, total_score
        FROM cuppings
        WHERE total_score IS NOT NULL AND cupper_name IS NOT NULL
        """,
    )
    if df.empty:
        return pd.DataFrame(), df

    df["consensus"] = df.groupby(["session_id", "roast_id"])["total_score"].transform("median")
    df["deviation"] = df["total_score"] - df["consensus"]
    df["session_order"] = pd.factorize(df["session_id"], sort=True)[0] + 1

    rows = []
    for cupper, group in df.groupby("cupper_name", sort=True):
        values = group["deviation"].to_numpy(float)
        n = len(values)
        mean = float(np.mean(values))
        if n > 1:
            se = float(stats.sem(values))
            crit = float(stats.t.ppf(0.975, n - 1))
            lo, hi = mean - crit * se, mean + crit * se
        else:
            lo = hi = mean
        excludes_zero = lo > 0 or hi < 0
        review = abs(mean) >= CALIBRATION_DRIFT_THRESHOLD and excludes_zero
        rows.append({
            "cupper": cupper, "n": n, "mean_deviation": mean,
            "ci_low": lo, "ci_high": hi,
            "status": "Review" if review else "Stable",
            "small_sample": n < SMALL_SAMPLE_WARN_N,
        })
    return pd.DataFrame(rows), df
