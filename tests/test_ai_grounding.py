"""Tests for the AI grounding layer: routing, real numbers, and gate carry-through."""

from __future__ import annotations

import pytest

from goodcup.ai import grounding as G
from goodcup.analysis.calibration import calibration_report
from goodcup.analysis.correlation import correlation_report
from goodcup.db import models
from goodcup.seed.generate import generate


@pytest.fixture()
def full_conn(tmp_path):
    db = tmp_path / "full.db"
    generate("full", db)
    conn = models.connect(db)
    yield conn
    conn.close()


@pytest.fixture()
def sparse_conn(tmp_path):
    db = tmp_path / "sparse.db"
    generate("sparse", db)
    conn = models.connect(db)
    yield conn
    conn.close()


def test_router_picks_the_right_analysis(full_conn):
    assert G.route_question(full_conn, "what drives cup score?").topic == "associations"
    assert G.route_question(full_conn, "is any cupper drifting?").topic == "calibration"
    assert G.route_question(full_conn, "which flavor notes track quality?").topic == "descriptors"
    assert G.route_question(full_conn, "recommend a roast profile").topic == "recommendation"
    assert G.route_question(full_conn, "is this lot consistent?").topic == "repeatability"


def test_association_facts_carry_the_real_numbers(full_conn):
    facts = G.gather_association_facts(full_conn)
    top = facts.summary_rows[0]
    # cross-check against the analysis layer directly
    df = correlation_report(full_conn, stratify=False).overall.to_frame().dropna(subset=["r"])
    lead = df.iloc[0]
    assert top["variable"] == lead["label"]
    assert top["r"] == round(float(lead["r"]), 2)
    assert top["n"] == int(lead["n"])


def test_calibration_facts_match_the_report(full_conn):
    facts = G.gather_calibration_facts(full_conn)
    status, _ = calibration_report(full_conn)
    assert {r["cupper"] for r in facts.summary_rows} == set(status["cupper"])
    flagged = [r["cupper"] for r in facts.summary_rows if r["status"] == "Review"]
    assert flagged == status[status["status"] == "Review"]["cupper"].tolist()


def test_recommendation_gate_is_carried_through_not_bypassed(sparse_conn):
    facts = G.route_question(sparse_conn, "recommend a roast profile")
    assert facts.topic == "recommendation"
    assert facts.available is False           # below the Phase-2 gate
    assert facts.summary_rows == []           # no fabricated neighbours
    assert "50" in facts.refusal              # explains the gate


def test_recommendation_available_above_gate(full_conn):
    facts = G.route_question(full_conn, "recommend a roast profile")
    assert facts.available is True
    assert len(facts.summary_rows) >= 1
