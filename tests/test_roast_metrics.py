"""Highest-priority tests (PRD 12): feed synthetic BT/time curves with KNOWN turning
point, phase boundaries, DTR and RoR features; assert the computed values match.

A wrong DTR/phase formula silently corrupts every downstream conclusion, so these
are written before anything consumes the metrics. Both degC and degF are exercised.
"""

from __future__ import annotations

import numpy as np
import pytest

from goodcup.analysis import roast_metrics as rm


# --------------------------------------------------------------------------- #
# Turning point
# --------------------------------------------------------------------------- #
def test_turning_point_is_min_bt_after_charge():
    times = np.arange(0, 240, 2, dtype=float)
    # BT falls from 200 to a clear minimum of 88 at t=60, then rises.
    bt = np.where(
        times <= 60,
        200 - (200 - 88) * (times / 60),
        88 + (times - 60) * 0.25,
    )
    tp_time, tp_temp = rm.turning_point(times, bt)
    assert tp_time == pytest.approx(60.0, abs=2.0)
    assert tp_temp == pytest.approx(88.0, abs=0.5)


# --------------------------------------------------------------------------- #
# Phase durations + DTR (from event markers -- independent of curve shape)
# --------------------------------------------------------------------------- #
def test_phase_metrics_and_dtr_exact():
    events = rm.RoastEvents(
        charge_time_s=0.0,
        dry_end_time_s=300.0,
        fc_start_time_s=480.0,
        drop_time_s=590.0,
    )
    m = rm.phase_metrics(events)
    assert m["total_time_s"] == pytest.approx(590.0)
    assert m["drying_time_s"] == pytest.approx(300.0)
    assert m["maillard_time_s"] == pytest.approx(180.0)
    assert m["development_time_s"] == pytest.approx(110.0)
    # DTR = (drop - fc_start) / (drop - charge) * 100 = 110/590*100
    assert m["dtr_pct"] == pytest.approx(110.0 / 590.0 * 100.0, abs=1e-6)


def test_phase_metrics_honours_nonzero_charge_time():
    events = rm.RoastEvents(
        charge_time_s=100.0,
        dry_end_time_s=400.0,
        fc_start_time_s=580.0,
        drop_time_s=690.0,
    )
    m = rm.phase_metrics(events)
    assert m["total_time_s"] == pytest.approx(590.0)
    assert m["development_time_s"] == pytest.approx(110.0)
    assert m["dtr_pct"] == pytest.approx(110.0 / 590.0 * 100.0, abs=1e-6)


def test_dtr_is_reported_not_judged():
    # A 30% DTR is unusual but the tool must report it, never clamp/flag it as wrong.
    events = rm.RoastEvents(charge_time_s=0, fc_start_time_s=70, drop_time_s=100)
    m = rm.phase_metrics(events)
    assert m["dtr_pct"] == pytest.approx(30.0)


# --------------------------------------------------------------------------- #
# Rate of Rise
# --------------------------------------------------------------------------- #
def test_ror_of_constant_slope_curve():
    # BT rises 0.1 degC/s == 6 degC/min, constant.
    times = np.arange(0, 300, 1, dtype=float)
    bt = 50.0 + 0.1 * times
    ror = rm.compute_ror(times, bt, window_s=30)
    assert ror.shape == times.shape
    # Interior (away from smoothing edges) should be ~6 deg/min.
    interior = ror[40:-40]
    assert np.nanmedian(interior) == pytest.approx(6.0, abs=0.1)


def test_ror_unit_is_preserved_for_fahrenheit():
    # Same numeric slope but the curve is in degF; RoR must be in degF/min,
    # i.e. the tool does not convert units under the hood.
    times = np.arange(0, 300, 1, dtype=float)
    bt_f = 120.0 + 0.2 * times  # 0.2 degF/s == 12 degF/min
    ror = rm.compute_ror(times, bt_f, window_s=30)
    assert np.nanmedian(ror[40:-40]) == pytest.approx(12.0, abs=0.2)


# --------------------------------------------------------------------------- #
# Crash / flick detection
# --------------------------------------------------------------------------- #
def test_detects_sharp_crash_and_subsequent_flick():
    t = np.arange(0, 121, 1, dtype=float)
    # RoR: flat ~15 until 30s, sharp crash to 8 by 60s (-7 over 30s), flick to 11 by 90s.
    ror = np.piecewise(
        t,
        [t <= 30, (t > 30) & (t <= 60), (t > 60) & (t <= 90), t > 90],
        [
            15.0,
            lambda x: 15.0 - (15.0 - 8.0) * (x - 30) / 30.0,
            lambda x: 8.0 + (11.0 - 8.0) * (x - 60) / 30.0,
            11.0,
        ],
    )
    res = rm.detect_crash_flick(t, ror, fc_start_time_s=0.0)
    assert res["ror_crash"] == 1
    assert res["ror_crash_severity"] == pytest.approx(7.0, abs=0.6)
    assert res["ror_flick"] == 1
    assert res["ror_flick_severity"] == pytest.approx(3.0, abs=0.6)


def test_gentle_decline_is_not_a_crash():
    # RoR declines gently by 7 over 120s (< threshold over any 30s window).
    t = np.arange(0, 121, 1, dtype=float)
    ror = 15.0 - 7.0 * (t / 120.0)
    res = rm.detect_crash_flick(t, ror, fc_start_time_s=0.0)
    assert res["ror_crash"] == 0


def test_no_crash_flick_without_first_crack_marker():
    t = np.arange(0, 60, 1, dtype=float)
    ror = 15.0 - 0.2 * t
    res = rm.detect_crash_flick(t, ror, fc_start_time_s=None)
    assert res["ror_crash"] == 0 and res["ror_flick"] == 0


# --------------------------------------------------------------------------- #
# Dry-end inference fallback (flagged)
# --------------------------------------------------------------------------- #
def test_dry_end_inferred_when_marker_absent():
    times = np.arange(0, 240, 2, dtype=float)
    # rises through 150 degC at t=120
    bt = 60.0 + (times / 240.0) * 180.0  # 60 -> 240, crosses 150 at t=120
    t_de, temp_de = rm.infer_dry_end(times, bt, temp_unit="C")
    assert t_de == pytest.approx(120.0, abs=2.0)
    assert temp_de == pytest.approx(150.0, abs=1.0)


# --------------------------------------------------------------------------- #
# End-to-end compute_metrics on a full synthetic roast
# --------------------------------------------------------------------------- #
def _synthetic_roast(dt=2.0):
    times = np.arange(0, 592, dt, dtype=float)
    # 0->60 charge dip to TP 90; then a rise through the phases to drop at 590.
    bt = np.empty_like(times)
    for i, t in enumerate(times):
        if t <= 60:
            bt[i] = 200 - (200 - 90) * (t / 60)
        else:
            bt[i] = 90 + (t - 60) * (210 - 90) / (590 - 60)
    return times, bt


def test_compute_metrics_end_to_end():
    times, bt = _synthetic_roast()
    events = rm.RoastEvents(
        charge_time_s=0.0,
        dry_end_time_s=300.0,
        fc_start_time_s=480.0,
        drop_time_s=590.0,
    )
    m = rm.compute_metrics(times, bt, events, temp_unit="C")
    d = m.as_derived_dict()
    assert d["turning_point_time_s"] == pytest.approx(60.0, abs=2.0)
    assert d["turning_point_temp"] == pytest.approx(90.0, abs=1.0)
    assert d["total_time_s"] == pytest.approx(590.0)
    assert d["dtr_pct"] == pytest.approx(110.0 / 590.0 * 100.0, abs=1e-6)
    assert d["dry_end_inferred"] == 0  # marker was provided
    # per-sample ror is aligned to the curve
    assert len(m.ror) == len(times)


def test_compute_metrics_infers_dry_end_when_missing():
    times, bt = _synthetic_roast()
    events = rm.RoastEvents(
        charge_time_s=0.0,
        dry_end_time_s=None,  # missing -> must be inferred + flagged
        fc_start_time_s=480.0,
        drop_time_s=590.0,
    )
    m = rm.compute_metrics(times, bt, events, temp_unit="C")
    d = m.as_derived_dict()
    assert d["dry_end_inferred"] == 1
    assert d["dry_end_time_s"] is not None
    assert d["drying_time_s"] == pytest.approx(d["dry_end_time_s"])
