"""Per-green learning-loop helpers used by the Lot History dashboard."""

from __future__ import annotations

import math

import pandas as pd


def require_single_temperature_unit(roasts: pd.DataFrame) -> str:
    """Return the lot's unit or refuse an unsafe mixed-unit overlay."""
    units = sorted({str(x).upper() for x in roasts.get("temp_unit", pd.Series(dtype=str)).dropna()})
    if not units:
        raise ValueError("No temperature unit is recorded for these roasts")
    if len(units) != 1 or units[0] not in {"C", "F"}:
        raise ValueError(f"Cannot compare mixed or unsupported temperature units: {', '.join(units)}")
    return units[0]


def repeatability_summary(roasts: pd.DataFrame) -> dict:
    """Summarize spread without pretending it is a universal quality grade."""
    def sd(column: str) -> float | None:
        values = pd.to_numeric(roasts.get(column), errors="coerce").dropna()
        if len(values) < 2:
            return None
        return float(values.std(ddof=1))

    score_sd = sd("mean_total_score")
    if score_sd is None:
        status = "Need more scored roasts"
    elif score_sd <= 0.5:
        status = "Tight score repeatability"
    elif score_sd <= 1.0:
        status = "Moderate score variation"
    else:
        status = "High score variation"

    n = len(roasts)
    curves = int(pd.to_numeric(roasts.get("curve_available"), errors="coerce").fillna(0).sum())
    return {
        "n_roasts": n,
        "score_sd": score_sd,
        "dtr_sd": sd("dtr_pct"),
        "drop_temp_sd": sd("drop_temp"),
        "total_time_sd": sd("total_time_s"),
        "curve_coverage": (curves / n) if n else math.nan,
        "status": status,
    }
