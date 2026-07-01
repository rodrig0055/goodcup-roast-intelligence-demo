"""Shared pytest fixtures.

``pythonpath = ["src"]`` in pyproject makes ``import goodcup...`` work without an
install; the editable install also works. ``config`` sits at repo root, which
pytest's rootdir puts on the path too.
"""

from __future__ import annotations

import sqlite3

import pytest

from goodcup.db import models


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """A fresh, schema-initialised in-memory database per test."""
    c = models.init_db(":memory:", reset=False)
    yield c
    c.close()


@pytest.fixture()
def tmp_db(tmp_path):
    """A schema-initialised file-backed database (for tests that re-open it)."""
    path = tmp_path / "goodcup_test.db"
    c = models.init_db(path, reset=True)
    c.close()
    return path


def make_green(conn, **overrides) -> int:
    data = {
        "lot_name": "Fixture Lot",
        "origin_country": "Ethiopia",
        "process": "washed",
        "density_g_per_l": 720.0,
        "moisture_pct": 10.5,
        "water_activity": 0.55,
        "altitude_masl": 1900.0,
        "screen_size": 15.0,
    }
    data.update(overrides)
    gid, _ = models.upsert_green(conn, data)
    return gid


def make_roast(conn, green_id, **overrides) -> int:
    data = {
        "green_id": green_id,
        "machine_id": "M1",
        "roaster_name": "Sam",
        "temp_unit": "C",
        "curve_available": 0,
    }
    data.update(overrides)
    rid, _ = models.upsert_roast(conn, data)
    return rid


def make_cupping(conn, roast_id, **overrides) -> int:
    data = {
        "roast_id": roast_id,
        "cupper_name": "Ana",
        "session_id": "S1",
        "form_type": "sca_traditional",
        "total_score": 84.0,
    }
    data.update(overrides)
    cid, _ = models.upsert_cupping(conn, data)
    return cid
