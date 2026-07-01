"""Ingest hand-entered data from the CSV templates in ``/templates``.

Three templates are supported, auto-detected by their columns:

* **green_intake.csv**  -> ``greens``
* **roast_manual.csv**  -> ``roasts`` (summary-only, ``curve_available = 0``; phase
  durations / DTR are still derived from any entered event times)
* **cupping_entry.csv** -> ``cuppings`` (linked to a roast by ``roast_ref``)

Empty cells become NULL. Re-ingesting the same file is idempotent (dedupe on a
content hash of the row's identifying fields).
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from goodcup.db import models
from goodcup.ingest.common import (
    ParsedRoast,
    content_hash,
    green_hash,
    resolve_roast_id,
    store_parsed_roast,
)

GREEN_NUMERIC = {
    "harvest_year": int,
    "altitude_masl": float,
    "density_g_per_l": float,
    "moisture_pct": float,
    "water_activity": float,
    "screen_size": float,
    "price_per_kg": float,
}
ROAST_NUMERIC = {
    "batch_size_g": float,
    "ambient_temp_c": float,
    "ambient_humidity_pct": float,
    "charge_temp": float,
    "dry_end_time_s": float,
    "dry_end_temp": float,
    "fc_start_time_s": float,
    "fc_start_temp": float,
    "fc_end_time_s": float,
    "drop_time_s": float,
    "drop_temp": float,
}
_SCORE_FIELDS = (
    "fragrance_aroma", "flavor", "aftertaste", "acidity", "body", "balance",
    "uniformity", "clean_cup", "sweetness", "overall", "defect_points", "total_score",
)
CUPPING_NUMERIC = {f: float for f in _SCORE_FIELDS}


def _clean(row: dict, numeric: dict) -> dict:
    out: dict = {}
    for k, v in row.items():
        if k is None:
            continue
        key = k.strip()
        s = v.strip() if isinstance(v, str) else v
        if s is None or s == "":
            out[key] = None
        elif key in numeric:
            try:
                out[key] = int(float(s)) if numeric[key] is int else float(s)
            except (ValueError, TypeError):
                out[key] = None
        else:
            out[key] = s
    return out


# --------------------------------------------------------------------------- #
# Per-entity ingest
# --------------------------------------------------------------------------- #
def _update_green(conn: sqlite3.Connection, green_id: int, data: dict) -> None:
    """Enrich an existing green with any provided non-null fields (greens are raw
    but editable -- only curve samples and cupping scores are trigger-locked)."""
    fields = {
        k: v
        for k, v in data.items()
        if v is not None and k not in ("lot_name", "source_hash")
    }
    if not fields:
        return
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE greens SET {assignments} WHERE green_id = ?",
        list(fields.values()) + [green_id],
    )
    conn.commit()


def ingest_greens(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    created = updated = 0
    for row in rows:
        data = _clean(row, GREEN_NUMERIC)
        if not data.get("lot_name"):
            continue
        data["source_hash"] = green_hash(data["lot_name"])
        gid, was_created = models.upsert_green(conn, data)
        if was_created:
            created += 1
        else:
            _update_green(conn, gid, data)
            updated += 1
    conn.commit()
    return {"kind": "greens", "created": created, "updated": updated}


def ingest_roasts(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    created = duplicate = 0
    for row in rows:
        data = _clean(row, ROAST_NUMERIC)
        lot = data.pop("lot_name", None)
        if not data.get("source_software"):
            data["source_software"] = "manual"
        src_hash = content_hash(
            "manual-roast", data.get("roast_ref"), data.get("roast_date"),
            data.get("machine_id"), lot,
        )
        res = store_parsed_roast(
            conn,
            ParsedRoast(
                roast={**data, "_lot_name": lot},
                green={"lot_name": lot},
                curve=[],
                roast_source_hash=src_hash,
            ),
        )
        created += int(res["created"])
        duplicate += int(not res["created"])
    return {"kind": "roasts", "created": created, "duplicate": duplicate}


def ingest_cuppings(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    created = duplicate = skipped = 0
    for row in rows:
        data = _clean(row, CUPPING_NUMERIC)
        roast_ref = data.pop("roast_ref", None)
        rid = resolve_roast_id(conn, roast_ref)
        if rid is None:
            skipped += 1
            continue
        data["roast_id"] = rid
        data["source_hash"] = content_hash(
            "manual-cupping", roast_ref, data.get("cupper_name"),
            data.get("session_id"), data.get("cupping_date"),
            data.get("form_type"), data.get("total_score"),
        )
        _, was_created = models.upsert_cupping(conn, data)
        created += int(was_created)
        duplicate += int(not was_created)
    conn.commit()
    return {"kind": "cuppings", "created": created, "duplicate": duplicate, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def _detect_kind(cols: set[str]) -> str:
    if "cupper_name" in cols:
        return "cuppings"
    if "charge_temp" in cols or "machine_id" in cols:
        return "roasts"
    if "lot_name" in cols:
        return "greens"
    raise ValueError(f"Unrecognised CSV template (columns: {sorted(cols)})")


def _read(path: str | Path) -> tuple[str, list[dict]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        cols = {c.strip() for c in (reader.fieldnames or [])}
        rows = list(reader)
    return _detect_kind(cols), rows


def ingest_file(conn: sqlite3.Connection, path: str | Path) -> dict:
    kind, rows = _read(path)
    dispatch = {"greens": ingest_greens, "roasts": ingest_roasts, "cuppings": ingest_cuppings}
    return dispatch[kind](conn, rows)


def ingest_dir(conn: sqlite3.Connection, directory: str | Path) -> list[dict]:
    """Ingest every CSV, ordered greens -> roasts -> cuppings so links resolve."""
    order = {"greens": 0, "roasts": 1, "cuppings": 2}
    files = []
    for p in sorted(Path(directory).glob("*.csv")):
        try:
            kind, rows = _read(p)
        except ValueError:
            continue  # not a manual template (e.g. a Cropster export)
        files.append((order[kind], kind, rows))
    results = []
    dispatch = {"greens": ingest_greens, "roasts": ingest_roasts, "cuppings": ingest_cuppings}
    for _, kind, rows in sorted(files, key=lambda x: x[0]):
        results.append(dispatch[kind](conn, rows))
    return results
