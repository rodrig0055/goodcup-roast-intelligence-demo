"""Derived roast metrics, computed exactly per PRD section 11.

This is the load-bearing math of the whole system: a wrong DTR or phase boundary
silently corrupts every correlation downstream. Its tests (tests/test_roast_metrics.py)
are written first and must stay green.

Everything works in the "seconds from CHARGE" convention. Temperature units are
*preserved*, never converted -- RoR of a degF curve is reported in degF/min. The
caller (ingest / seed) is responsible for zeroing time at charge and recording the
unit; this module never guesses a unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Optional

import numpy as np

from config import (
    DRY_END_TEMP_FALLBACK_C,
    DRY_END_TEMP_FALLBACK_F,
    ROR_CRASH_DROP,
    ROR_CRASH_WINDOW_S,
    ROR_FLICK_RISE,
    ROR_SMOOTHING_WINDOW_S,
    TEMP_UNIT_F,
)


# --------------------------------------------------------------------------- #
# Event markers
# --------------------------------------------------------------------------- #
@dataclass
class RoastEvents:
    """Event times in seconds from CHARGE (charge is usually 0)."""

    charge_time_s: float = 0.0
    dry_end_time_s: Optional[float] = None
    fc_start_time_s: Optional[float] = None
    fc_end_time_s: Optional[float] = None
    drop_time_s: Optional[float] = None


@dataclass
class RoastMetrics:
    """Computed derived metrics for one roast, ready for DB writeback."""

    turning_point_time_s: Optional[float]
    turning_point_temp: Optional[float]
    total_time_s: Optional[float]
    drying_time_s: Optional[float]
    maillard_time_s: Optional[float]
    development_time_s: Optional[float]
    dtr_pct: Optional[float]
    dry_end_time_s: Optional[float]
    dry_end_temp: Optional[float]
    dry_end_inferred: int
    ror_crash: int
    ror_crash_severity: Optional[float]
    ror_flick: int
    ror_flick_severity: Optional[float]
    ror: np.ndarray = field(default_factory=lambda: np.array([]))

    def as_derived_dict(self) -> dict:
        """The subset of columns written to ``roasts`` (raw event fields are only
        included when dry-end had to be *inferred*, never otherwise)."""
        d = {
            "turning_point_temp": _f(self.turning_point_temp),
            "turning_point_time_s": _f(self.turning_point_time_s),
            "total_time_s": _f(self.total_time_s),
            "drying_time_s": _f(self.drying_time_s),
            "maillard_time_s": _f(self.maillard_time_s),
            "development_time_s": _f(self.development_time_s),
            "dtr_pct": _f(self.dtr_pct),
            "dry_end_inferred": int(self.dry_end_inferred),
            "ror_crash": int(self.ror_crash),
            "ror_crash_severity": _f(self.ror_crash_severity),
            "ror_flick": int(self.ror_flick),
            "ror_flick_severity": _f(self.ror_flick_severity),
        }
        if self.dry_end_inferred:
            d["dry_end_time_s"] = _f(self.dry_end_time_s)
            d["dry_end_temp"] = _f(self.dry_end_temp)
        return d


def _f(x) -> Optional[float]:
    return None if x is None else float(x)


# --------------------------------------------------------------------------- #
# Turning point
# --------------------------------------------------------------------------- #
def turning_point(times, bt) -> tuple[float, float]:
    """Minimum of the BT curve after charge. Returns ``(time_s, temp)``."""
    times = np.asarray(times, dtype=float)
    bt = np.asarray(bt, dtype=float)
    mask = times >= 0
    idx = int(np.nanargmin(bt[mask]))
    t = times[mask][idx]
    return float(t), float(bt[mask][idx])


# --------------------------------------------------------------------------- #
# Phase durations + DTR
# --------------------------------------------------------------------------- #
def phase_metrics(events: RoastEvents) -> dict:
    """Phase durations and DTR from event markers (PRD 11)."""
    c = events.charge_time_s or 0.0
    de, fc, drop = events.dry_end_time_s, events.fc_start_time_s, events.drop_time_s

    total = (drop - c) if drop is not None else None
    drying = (de - c) if de is not None else None
    maillard = (fc - de) if (fc is not None and de is not None) else None
    development = (drop - fc) if (drop is not None and fc is not None) else None
    dtr = (
        (development / total * 100.0)
        if (development is not None and total not in (None, 0))
        else None
    )
    return {
        "total_time_s": total,
        "drying_time_s": drying,
        "maillard_time_s": maillard,
        "development_time_s": development,
        "dtr_pct": dtr,
    }


# --------------------------------------------------------------------------- #
# Rate of Rise
# --------------------------------------------------------------------------- #
def _moving_average(y: np.ndarray, n: int) -> np.ndarray:
    """Centred moving average of window ``n`` samples (edge-padded, length-preserving)."""
    if n <= 1:
        return y
    if n % 2 == 0:
        n += 1
    pad = n // 2
    ypad = np.pad(y, pad, mode="edge")
    kernel = np.ones(n) / n
    return np.convolve(ypad, kernel, mode="valid")


def compute_ror(times, bt, window_s: int = ROR_SMOOTHING_WINDOW_S) -> np.ndarray:
    """Smoothed Rate of Rise = d(BT)/dt in degrees per MINUTE, per sample.

    Instantaneous slope via ``np.gradient`` (handles non-uniform spacing and the
    endpoints), then a centred rolling mean spanning ~``window_s`` seconds. Units
    follow the input curve: a degF curve yields degF/min.
    """
    times = np.asarray(times, dtype=float)
    bt = np.asarray(bt, dtype=float)
    if times.size < 2:
        return np.zeros_like(bt)
    slope_per_s = np.gradient(bt, times)
    ror_per_min = slope_per_s * 60.0
    dt = np.median(np.diff(times))
    window_samples = max(1, int(round(window_s / dt))) if dt > 0 else 1
    return _moving_average(ror_per_min, window_samples)


# --------------------------------------------------------------------------- #
# Crash / flick detection
# --------------------------------------------------------------------------- #
def detect_crash_flick(
    times,
    ror,
    fc_start_time_s: Optional[float],
    crash_drop: float = ROR_CRASH_DROP,
    crash_window_s: float = ROR_CRASH_WINDOW_S,
    flick_rise: float = ROR_FLICK_RISE,
) -> dict:
    """Flag a RoR crash (sharp sustained drop after first crack) and a subsequent
    flick (upturn), with severities. Heuristic (documented, thresholds in config):

    * **Crash** -- over any trailing window of ``crash_window_s`` seconds within the
      development phase, RoR falls by at least ``crash_drop`` deg/min. Measuring the
      drop over a fixed short window is what separates a *sharp* crash from a gentle,
      normal decline spread across the whole phase. Severity = the steepest such drop.
    * **Flick** -- after the post-FC RoR low point, RoR rises again by at least
      ``flick_rise`` deg/min. Severity = that rebound. Only considered when a crash
      was detected.

    Returns integer flags (0/1) and float severities, ready for DB writeback.
    """
    zero = {
        "ror_crash": 0,
        "ror_crash_severity": 0.0,
        "ror_flick": 0,
        "ror_flick_severity": 0.0,
    }
    if fc_start_time_s is None:
        return zero
    times = np.asarray(times, dtype=float)
    ror = np.asarray(ror, dtype=float)
    mask = times >= fc_start_time_s
    if mask.sum() < 2:
        return zero
    t, r = times[mask], ror[mask]

    # --- crash: steepest drop over a trailing crash_window_s ------------------
    max_drop = 0.0
    for i in range(len(t)):
        if t[i] - t[0] < crash_window_s:
            continue  # not enough history for a full window yet
        r_before = float(np.interp(t[i] - crash_window_s, t, r))
        drop = r_before - r[i]
        if drop > max_drop:
            max_drop = drop
    crash = 1 if max_drop >= crash_drop else 0

    # --- flick: rebound after the post-FC low (only meaningful after a crash) --
    flick = 0
    flick_sev = 0.0
    if crash:
        bottom = int(np.argmin(r))
        if bottom < len(r) - 1:
            rebound = float(np.max(r[bottom:]) - r[bottom])
            flick_sev = rebound
            flick = 1 if rebound >= flick_rise else 0

    return {
        "ror_crash": crash,
        "ror_crash_severity": float(max_drop),
        "ror_flick": flick,
        "ror_flick_severity": float(flick_sev),
    }


# --------------------------------------------------------------------------- #
# Dry-end inference fallback (flagged)
# --------------------------------------------------------------------------- #
def infer_dry_end(times, bt, temp_unit: str = "C") -> tuple[Optional[float], Optional[float]]:
    """Infer dry-end (yellowing) as the first BT crossing of the configured
    temperature threshold, interpolated. Returns ``(time_s, temp)`` or ``(None, None)``.
    Callers must flag this as inferred (``dry_end_inferred = 1``)."""
    threshold = (
        DRY_END_TEMP_FALLBACK_F if temp_unit == TEMP_UNIT_F else DRY_END_TEMP_FALLBACK_C
    )
    times = np.asarray(times, dtype=float)
    bt = np.asarray(bt, dtype=float)
    above = np.where(bt >= threshold)[0]
    if above.size == 0:
        return None, None
    i = int(above[0])
    if i == 0:
        return float(times[0]), float(bt[0])
    t0, t1 = times[i - 1], times[i]
    b0, b1 = bt[i - 1], bt[i]
    t_cross = t1 if b1 == b0 else t0 + (threshold - b0) * (t1 - t0) / (b1 - b0)
    return float(t_cross), float(threshold)


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def compute_metrics(
    times,
    bt,
    events: RoastEvents,
    temp_unit: str = "C",
    et=None,
    ror_window_s: int = ROR_SMOOTHING_WINDOW_S,
) -> RoastMetrics:
    """Compute all derived metrics for one roast from its curve + event markers."""
    times = np.asarray(times, dtype=float)
    bt = np.asarray(bt, dtype=float)

    tp_time, tp_temp = turning_point(times, bt)

    dry_end_inferred = 0
    dry_end_temp = None
    ev = events
    if ev.dry_end_time_s is None:
        de_time, de_temp = infer_dry_end(times, bt, temp_unit=temp_unit)
        if de_time is not None:
            ev = replace(events, dry_end_time_s=de_time)
            dry_end_inferred = 1
            dry_end_temp = de_temp

    phases = phase_metrics(ev)
    ror = compute_ror(times, bt, window_s=ror_window_s)
    cf = detect_crash_flick(times, ror, ev.fc_start_time_s)

    return RoastMetrics(
        turning_point_time_s=tp_time,
        turning_point_temp=tp_temp,
        total_time_s=phases["total_time_s"],
        drying_time_s=phases["drying_time_s"],
        maillard_time_s=phases["maillard_time_s"],
        development_time_s=phases["development_time_s"],
        dtr_pct=phases["dtr_pct"],
        dry_end_time_s=ev.dry_end_time_s,
        dry_end_temp=dry_end_temp,
        dry_end_inferred=dry_end_inferred,
        ror_crash=cf["ror_crash"],
        ror_crash_severity=cf["ror_crash_severity"],
        ror_flick=cf["ror_flick"],
        ror_flick_severity=cf["ror_flick_severity"],
        ror=ror,
    )
