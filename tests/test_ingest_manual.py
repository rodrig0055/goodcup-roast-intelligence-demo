"""Manual-CSV ingest: template round-trips, summary-only phase metrics, cupping
linkage to roasts ingested from logs, and dedupe (PRD 12)."""

from __future__ import annotations

import pytest

from config import SAMPLES_DIR, TEMPLATES_DIR
from goodcup.db import models
from goodcup.ingest import artisan, cropster, manual_csv


def test_manual_green_and_roast_templates(conn):
    g = manual_csv.ingest_file(conn, TEMPLATES_DIR / "green_intake.csv")
    assert g["kind"] == "greens" and g["created"] == 1

    r = manual_csv.ingest_file(conn, TEMPLATES_DIR / "roast_manual.csv")
    assert r["kind"] == "roasts" and r["created"] == 1

    row = conn.execute("SELECT * FROM roasts WHERE roast_ref = 'R-2026-014'").fetchone()
    assert row["curve_available"] == 0  # summary-only paper log
    # phase metrics are still derived from the entered event times
    assert row["total_time_s"] == pytest.approx(590.0)
    assert row["dtr_pct"] == pytest.approx((590 - 480) / 590 * 100, abs=1e-6)
    # no curve -> turning point stays null
    assert row["turning_point_time_s"] is None


def test_manual_roast_reimport_is_idempotent(conn):
    manual_csv.ingest_file(conn, TEMPLATES_DIR / "roast_manual.csv")
    second = manual_csv.ingest_file(conn, TEMPLATES_DIR / "roast_manual.csv")
    assert second["duplicate"] == 1 and second["created"] == 0
    assert conn.execute(
        "SELECT COUNT(*) AS n FROM roasts WHERE roast_ref = 'R-2026-014'"
    ).fetchone()["n"] == 1


def test_cupping_sheet_links_to_logged_roasts(conn):
    # roasts must exist first (from the roast logs) for cuppings to attach
    artisan.ingest_dir(conn, SAMPLES_DIR)
    cropster.ingest_file(conn, SAMPLES_DIR / "sample_cropster_R-2026-003.csv")

    res = manual_csv.ingest_file(conn, SAMPLES_DIR / "sample_cupping_SES-2026-02.csv")
    assert res["kind"] == "cuppings"
    assert res["created"] == 6  # 2 cuppers x 3 roasts
    assert res["skipped"] == 0
    assert models.count_matched_roasts(conn) == 3


def test_cupping_reimport_is_idempotent(conn):
    artisan.ingest_dir(conn, SAMPLES_DIR)
    cropster.ingest_file(conn, SAMPLES_DIR / "sample_cropster_R-2026-003.csv")
    manual_csv.ingest_file(conn, SAMPLES_DIR / "sample_cupping_SES-2026-02.csv")
    second = manual_csv.ingest_file(conn, SAMPLES_DIR / "sample_cupping_SES-2026-02.csv")
    assert second["created"] == 0 and second["duplicate"] == 6
    assert conn.execute("SELECT COUNT(*) AS n FROM cuppings").fetchone()["n"] == 6


def test_cupping_without_matching_roast_is_skipped(conn):
    # no roasts ingested -> every cupping row is skipped, not attached blindly
    res = manual_csv.ingest_file(conn, SAMPLES_DIR / "sample_cupping_SES-2026-02.csv")
    assert res["created"] == 0 and res["skipped"] == 6


def test_ingest_dir_orders_greens_roasts_cuppings(conn):
    # dumping every manual CSV in one call must still resolve links
    artisan.ingest_dir(conn, SAMPLES_DIR)  # provides roasts for the cupping refs
    results = manual_csv.ingest_dir(conn, SAMPLES_DIR)
    kinds = [r["kind"] for r in results]
    # cuppings processed after greens/roasts
    assert kinds == sorted(kinds, key=lambda k: {"greens": 0, "roasts": 1, "cuppings": 2}[k])
