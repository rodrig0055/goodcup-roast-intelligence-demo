"""Round-trip the Cropster parser on the synthetic fixture (PRD 12)."""

from __future__ import annotations

import pytest

from config import SAMPLES_DIR
from goodcup.ingest import cropster

FIXTURE = SAMPLES_DIR / "sample_cropster_R-2026-003.csv"


def test_cropster_roundtrip(conn):
    res = cropster.ingest_file(conn, FIXTURE)
    assert res["created"] is True
    assert res["n_curve"] > 250

    row = conn.execute("SELECT * FROM roasts WHERE roast_id = ?", (res["roast_id"],)).fetchone()
    assert row["roast_ref"] == "R-2026-003"
    assert row["source_software"] == "cropster"
    assert row["machine_id"] == "Loring-S15"
    assert row["temp_unit"] == "C"
    assert row["curve_available"] == 1
    assert row["dry_end_time_s"] == pytest.approx(310.0, abs=2.0)
    assert row["fc_start_time_s"] == pytest.approx(486.0, abs=2.0)
    assert row["drop_time_s"] == pytest.approx(602.0, abs=2.0)


def test_cropster_metrics_and_green_linked(conn):
    res = cropster.ingest_file(conn, FIXTURE)
    row = conn.execute("SELECT * FROM roasts WHERE roast_id = ?", (res["roast_id"],)).fetchone()
    assert row["dtr_pct"] == pytest.approx((602 - 486) / 602 * 100, abs=1.0)
    green = conn.execute("SELECT lot_name FROM greens WHERE green_id = ?", (row["green_id"],)).fetchone()
    assert green["lot_name"] == "Huila Pink Bourbon"


def test_cropster_reimport_is_idempotent(conn):
    cropster.ingest_file(conn, FIXTURE)
    second = cropster.ingest_file(conn, FIXTURE)
    assert second["created"] is False and second["n_curve"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM roasts").fetchone()["n"] == 1
