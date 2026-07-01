"""Tests for SPC monitoring: consensus control chart and metric stability."""

from __future__ import annotations

import pytest

from goodcup.analysis.monitoring import consensus_control_chart, metric_stability

from conftest import make_cupping, make_green, make_roast


def _stable_then_spike(conn):
    g = make_green(conn)
    for i in range(8):
        r = make_roast(conn, g)
        make_cupping(conn, r, session_id=f"S{i:02d}", cupping_date=f"2026-01-{i + 1:02d}",
                     total_score=84.0 + (i % 2) * 0.3)
    r = make_roast(conn, g)
    make_cupping(conn, r, session_id="S99", cupping_date="2026-02-01", total_score=95.0)
    return g


def test_control_chart_flags_only_the_out_of_control_session(conn):
    _stable_then_spike(conn)
    chart = consensus_control_chart(conn)
    assert chart.n_out == 1
    flagged = chart.points[chart.points["out_of_control"]]["label"].tolist()
    assert flagged == ["S99"]
    assert chart.lower < chart.center < chart.upper


def test_control_chart_flags_nothing_when_stable(conn):
    g = make_green(conn)
    for i in range(8):
        r = make_roast(conn, g)
        make_cupping(conn, r, session_id=f"S{i:02d}", cupping_date=f"2026-01-{i + 1:02d}",
                     total_score=84.0 + (i % 2) * 0.2)
    chart = consensus_control_chart(conn)
    assert chart.n_out == 0


def test_empty_database_returns_empty_chart(conn):
    chart = consensus_control_chart(conn)
    assert chart.points.empty
    assert chart.n_out == 0


def test_metric_stability_ranks_least_repeatable_first(conn):
    tight = make_green(conn, lot_name="Tight Lot")
    loose = make_green(conn, lot_name="Loose Lot")
    for dtr in (18.0, 18.2, 17.9):
        make_roast(conn, tight, dtr_pct=dtr)
    for dtr in (14.0, 22.0, 18.0):
        make_roast(conn, loose, dtr_pct=dtr)
    stability = metric_stability(conn, "dtr_pct")
    assert list(stability["lot_name"])[0] == "Loose Lot"      # highest CV first
    assert stability.set_index("lot_name").loc["Loose Lot", "cv_pct"] > \
        stability.set_index("lot_name").loc["Tight Lot", "cv_pct"]


def test_metric_stability_rejects_unknown_metric(conn):
    with pytest.raises(ValueError):
        metric_stability(conn, "not_a_metric")
