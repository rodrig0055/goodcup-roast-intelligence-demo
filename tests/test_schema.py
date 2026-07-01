"""Schema integrity: FK enforcement, raw-table immutability, dedupe, views (PRD 12)."""

from __future__ import annotations

import sqlite3

import pytest

from goodcup.db import models
from tests.conftest import make_cupping, make_green, make_roast


def test_all_tables_and_views_exist(conn):
    names = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    }
    assert {"greens", "roasts", "roast_curves", "cuppings", "descriptors"} <= names
    assert {"matched_roasts", "roast_cupping"} <= names


def test_foreign_keys_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO roasts (green_id) VALUES (99999)")


def test_roast_curve_raw_columns_immutable(conn):
    gid = make_green(conn)
    rid = make_roast(conn, gid, curve_available=1)
    models.insert_curve_points(conn, rid, [{"time_s": 0, "bean_temp": 200, "env_temp": 210}])

    for col in ("time_s", "bean_temp", "env_temp"):
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute(f"UPDATE roast_curves SET {col} = 1 WHERE roast_id = ?", (rid,))


def test_roast_curve_derived_ror_is_writable(conn):
    gid = make_green(conn)
    rid = make_roast(conn, gid, curve_available=1)
    models.insert_curve_points(conn, rid, [{"time_s": 0, "bean_temp": 200}])
    # ror is DERIVED -> updating it must be allowed (recomputable)
    conn.execute("UPDATE roast_curves SET ror = 12.5 WHERE roast_id = ?", (rid,))
    row = conn.execute("SELECT ror FROM roast_curves WHERE roast_id = ?", (rid,)).fetchone()
    assert row["ror"] == 12.5


def test_cupping_raw_scores_immutable(conn):
    gid = make_green(conn)
    rid = make_roast(conn, gid)
    cid = make_cupping(conn, rid, total_score=84.0, flavor=7.5)
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("UPDATE cuppings SET flavor = 9.0 WHERE cupping_id = ?", (cid,))


def test_curve_sample_unique_and_idempotent(conn):
    gid = make_green(conn)
    rid = make_roast(conn, gid, curve_available=1)
    pts = [{"time_s": 0, "bean_temp": 200}, {"time_s": 5, "bean_temp": 150}]
    assert models.insert_curve_points(conn, rid, pts) == 2
    # re-inserting the same samples adds nothing
    assert models.insert_curve_points(conn, rid, pts) == 0
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM roast_curves WHERE roast_id = ?", (rid,)
    ).fetchone()["n"]
    assert count == 2


def test_source_hash_dedupe_across_entities(conn):
    gid1, created1 = models.upsert_green(conn, {"lot_name": "A", "source_hash": "h1"})
    gid2, created2 = models.upsert_green(conn, {"lot_name": "A", "source_hash": "h1"})
    assert created1 is True and created2 is False and gid1 == gid2


def test_matched_roasts_view_counts_only_scored(conn):
    gid = make_green(conn)
    r_scored = make_roast(conn, gid)
    make_cupping(conn, r_scored, total_score=85.0)
    make_roast(conn, gid)  # roast with no cupping -> not matched
    assert models.count_matched_roasts(conn) == 1


def test_matched_roasts_view_averages_multiple_cuppers(conn):
    gid = make_green(conn)
    rid = make_roast(conn, gid)
    make_cupping(conn, rid, cupper_name="Ana", total_score=84.0)
    make_cupping(conn, rid, cupper_name="Ben", total_score=86.0, source_hash="c-ben")
    row = conn.execute(
        "SELECT mean_total_score, n_cuppings FROM matched_roasts WHERE roast_id = ?",
        (rid,),
    ).fetchone()
    assert row["n_cuppings"] == 2
    assert row["mean_total_score"] == pytest.approx(85.0)
