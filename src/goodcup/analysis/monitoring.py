"""Statistical process control (SPC) for cupping consensus and roast stability.

Two honest, classical control charts, no black boxes:

* ``consensus_control_chart`` tracks the panel consensus (median cup score) per
  cupping session over time, with 3-sigma limits estimated from the series'
  own variation. Points outside the limits are flagged as *out of control* --
  a prompt to investigate (a green change, a calibration slip, a process shift),
  never an automatic verdict.
* ``metric_stability`` reports how repeatable a roast metric is across roasts of
  the same green lot (mean, SD, coefficient of variation), so drift in the
  process itself is visible next to drift in the panel.

Limits use the mean-moving-range estimator (MR-bar / 1.128), the standard
individuals-chart approach, which is robust for the short series a lab produces.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from goodcup.db import models

#: d2 constant for a moving range of n=2 (individuals / MR chart).
_D2_N2 = 1.128


@dataclass
class ControlChart:
    center: float
    lower: float
    upper: float
    points: pd.DataFrame          # columns: label, value, out_of_control
    n_out: int


def _individuals_limits(values: np.ndarray) -> tuple[float, float, float]:
    """Center line and 3-sigma control limits via the mean moving range."""
    center = float(np.mean(values))
    if len(values) < 2:
        return center, center, center
    mr_bar = float(np.mean(np.abs(np.diff(values))))
    sigma = mr_bar / _D2_N2
    return center, center - 3 * sigma, center + 3 * sigma


def consensus_control_chart(conn) -> ControlChart:
    """Control chart of per-session panel consensus (median total score)."""
    df = models.read_sql(
        conn,
        """
        SELECT session_id, cupping_date, total_score
        FROM cuppings
        WHERE total_score IS NOT NULL AND session_id IS NOT NULL
        """,
    )
    if df.empty:
        empty = pd.DataFrame(columns=["label", "value", "out_of_control"])
        return ControlChart(float("nan"), float("nan"), float("nan"), empty, 0)

    per_session = (
        df.groupby("session_id")
        .agg(value=("total_score", "median"), date=("cupping_date", "min"))
        .sort_values("date")
        .reset_index()
    )
    values = per_session["value"].to_numpy(float)
    center, lower, upper = _individuals_limits(values)
    per_session["out_of_control"] = (values < lower) | (values > upper)
    points = per_session.rename(columns={"session_id": "label"})[["label", "value", "out_of_control"]]
    return ControlChart(center, lower, upper, points, int(points["out_of_control"].sum()))


def metric_stability(conn, metric: str = "dtr_pct") -> pd.DataFrame:
    """Per-green-lot repeatability of a roast metric across its roasts.

    Returns one row per lot with N, mean, SD, and coefficient of variation (%),
    ordered by least stable first. Lots with a single roast report SD = NaN.
    """
    allowed = {"dtr_pct", "drop_temp", "total_time_s", "development_time_s", "charge_temp"}
    if metric not in allowed:
        raise ValueError(f"metric must be one of {sorted(allowed)}")
    df = models.read_sql(
        conn,
        f"""
        SELECT g.lot_name, r.{metric} AS value
        FROM roasts r JOIN greens g ON g.green_id = r.green_id
        WHERE r.{metric} IS NOT NULL
        """,
    )
    if df.empty:
        return pd.DataFrame(columns=["lot_name", "n", "mean", "sd", "cv_pct"])
    rows = []
    for lot, g in df.groupby("lot_name"):
        vals = g["value"].to_numpy(float)
        mean = float(np.mean(vals))
        sd = float(np.std(vals, ddof=1)) if len(vals) > 1 else float("nan")
        cv = float(sd / mean * 100) if len(vals) > 1 and mean else float("nan")
        rows.append({"lot_name": lot, "n": len(vals), "mean": mean, "sd": sd, "cv_pct": cv})
    out = pd.DataFrame(rows)
    return out.sort_values("cv_pct", ascending=False, na_position="last").reset_index(drop=True)
