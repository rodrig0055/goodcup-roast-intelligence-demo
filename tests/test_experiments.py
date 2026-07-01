"""Tests for durable experiment decision records and cited-reference links."""

from __future__ import annotations

from goodcup.db import models


def test_experiment_persists_and_round_trips(conn):
    eid, created = models.upsert_experiment(conn, {
        "created_at": "2026-07-01", "title": "DTR boundary test",
        "hypothesis": "higher DTR -> higher score", "variable": "Development time",
        "success_rule": "lead >= 0.5", "status": "decided",
        "decision": "Advance Treatment A", "owner": "Head Roaster",
        "source_hash": "exp-1",
    })
    assert created is True
    rows = models.list_experiments(conn)
    assert len(rows) == 1
    assert rows.iloc[0]["title"] == "DTR boundary test"
    assert rows.iloc[0]["decision"] == "Advance Treatment A"


def test_experiment_dedupes_on_source_hash(conn):
    first, c1 = models.upsert_experiment(conn, {"title": "T", "source_hash": "dup"})
    second, c2 = models.upsert_experiment(conn, {"title": "T again", "source_hash": "dup"})
    assert first == second
    assert c1 is True and c2 is False
    assert len(models.list_experiments(conn)) == 1


def test_reference_link_scopes_to_experiment(conn):
    eid, _ = models.upsert_experiment(conn, {"title": "T", "source_hash": "exp"})
    ref_a, _ = models.upsert_reference(conn, {"title": "Paper A", "source_hash": "a"})
    ref_b, _ = models.upsert_reference(conn, {"title": "Paper B", "source_hash": "b"})
    models.link_reference_to_experiment(conn, eid, ref_a)
    models.link_reference_to_experiment(conn, eid, ref_a)  # idempotent

    cited = models.list_references(conn, experiment_id=eid)
    assert len(cited) == 1                       # only the linked one, no dup
    assert cited.iloc[0]["title"] == "Paper A"
    assert len(models.list_references(conn)) == 2  # both remain in the cache
