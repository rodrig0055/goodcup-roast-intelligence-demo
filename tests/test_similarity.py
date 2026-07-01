"""Tests for the gated recommender and interpretable predictor.

The gate is the product: below the data threshold we must refuse, above it we
must return real neighbours and an interpretable model. We drive this with the
seed scenarios (``sparse`` below the gate, ``full`` above it) rather than hand
-building 50 roasts.
"""

from __future__ import annotations

import pytest

from config import PHASE2_MIN_MATCHED_ROASTS
from goodcup.db import models
from goodcup.recommend.similarity import (
    NUMERIC_FEATURES,
    fit_score_predictor,
    recommend_for_green,
)
from goodcup.seed.generate import generate


@pytest.fixture()
def sparse_conn(tmp_path):
    db = tmp_path / "sparse.db"
    generate("sparse", db)
    conn = models.connect(db)
    yield conn
    conn.close()


@pytest.fixture()
def full_conn(tmp_path):
    db = tmp_path / "full.db"
    generate("full", db)
    conn = models.connect(db)
    yield conn
    conn.close()


def test_recommender_refuses_below_the_gate(sparse_conn):
    assert models.count_matched_roasts(sparse_conn) < PHASE2_MIN_MATCHED_ROASTS
    gid = sparse_conn.execute("SELECT green_id FROM greens LIMIT 1").fetchone()[0]
    rec = recommend_for_green(sparse_conn, gid)
    assert rec.available is False
    assert str(PHASE2_MIN_MATCHED_ROASTS) in rec.reason      # explains the gate
    assert rec.neighbors == []                               # nothing fabricated


def test_predictor_refuses_below_the_gate(sparse_conn):
    model = fit_score_predictor(sparse_conn)
    assert model.available is False
    assert model.coefficients == {}


def test_recommender_returns_real_neighbors_above_the_gate(full_conn):
    assert models.count_matched_roasts(full_conn) >= PHASE2_MIN_MATCHED_ROASTS
    gid = full_conn.execute("SELECT green_id FROM greens LIMIT 1").fetchone()[0]
    rec = recommend_for_green(full_conn, gid)
    assert rec.available is True
    assert len(rec.neighbors) >= 1
    # neighbours are real roasts with the interpretability breakdown
    valid_ids = {int(r[0]) for r in full_conn.execute("SELECT roast_id FROM roasts").fetchall()}
    for nb in rec.neighbors:
        assert nb["roast_id"] in valid_ids
        assert 0.0 <= nb["similarity"] <= 1.0
        for feat in ("dtr_pct", "development_time_s", "drop_temp"):
            assert feat in nb
    # ranked best-score first
    scores = [nb["mean_total_score"] for nb in rec.neighbors]
    assert scores == sorted(scores, reverse=True)


def test_predictor_is_interpretable_above_the_gate(full_conn):
    model = fit_score_predictor(full_conn)
    assert model.available is True
    assert set(model.coefficients) == set(NUMERIC_FEATURES)   # one weight per feature
    # planted signal: DTR should carry a positive weight
    assert model.coefficients["dtr_pct"] > 0
