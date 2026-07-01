"""Round-trip the Artisan parser on the synthetic fixtures (PRD 12)."""

from __future__ import annotations

import pytest

from config import SAMPLES_DIR
from goodcup.db import models
from goodcup.ingest import artisan

FIXTURE = SAMPLES_DIR / "sample_artisan_R-2026-001.alog"


def test_artisan_roundtrip_lands_rows_and_events(conn):
    res = artisan.ingest_file(conn, FIXTURE)
    assert res["created"] is True
    assert res["n_curve"] > 250

    row = conn.execute("SELECT * FROM roasts WHERE roast_id = ?", (res["roast_id"],)).fetchone()
    assert row["roast_ref"] == "R-2026-001"
    assert row["source_software"] == "artisan"
    assert row["temp_unit"] == "C"
    assert row["curve_available"] == 1
    assert row["machine_id"] == "Probat-P12"

    # event times (seconds from charge) survive the round-trip exactly
    assert row["dry_end_time_s"] == pytest.approx(298.0, abs=2.0)
    assert row["fc_start_time_s"] == pytest.approx(474.0, abs=2.0)
    assert row["drop_time_s"] == pytest.approx(588.0, abs=2.0)


def test_artisan_derived_metrics_are_computed(conn):
    res = artisan.ingest_file(conn, FIXTURE)
    row = conn.execute("SELECT * FROM roasts WHERE roast_id = ?", (res["roast_id"],)).fetchone()
    assert row["total_time_s"] == pytest.approx(588.0, abs=2.0)
    assert row["turning_point_time_s"] == pytest.approx(68.0, abs=8.0)
    assert row["turning_point_temp"] == pytest.approx(91.0, abs=2.0)
    assert row["dtr_pct"] == pytest.approx((588 - 474) / 588 * 100, abs=1.0)

    # per-sample RoR was written back to the curve
    ror_rows = conn.execute(
        "SELECT ror FROM roast_curves WHERE roast_id = ? AND ror IS NOT NULL",
        (res["roast_id"],),
    ).fetchall()
    assert len(ror_rows) > 250


def test_artisan_reimport_is_idempotent(conn):
    first = artisan.ingest_file(conn, FIXTURE)
    second = artisan.ingest_file(conn, FIXTURE)
    assert first["created"] is True
    assert second["created"] is False
    assert second["n_curve"] == 0
    n_roasts = conn.execute("SELECT COUNT(*) AS n FROM roasts").fetchone()["n"]
    n_curves = conn.execute("SELECT COUNT(*) AS n FROM roast_curves").fetchone()["n"]
    assert n_roasts == 1
    assert n_curves == first["n_curve"]


def test_ingest_dir_loads_both_artisan_profiles(conn):
    results = artisan.ingest_dir(conn, SAMPLES_DIR)
    assert len(results) == 2  # two .alog fixtures
    assert all(r["created"] for r in results)
    assert conn.execute("SELECT COUNT(*) AS n FROM roasts").fetchone()["n"] == 2
