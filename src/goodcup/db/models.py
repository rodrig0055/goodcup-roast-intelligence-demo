"""Typed-ish access layer over the SQLite store (stdlib ``sqlite3`` only).

No ORM: the PRD asks for the lighter option, and a single-user local file does not
need one. These helpers do three things:

* open connections with foreign-key enforcement on (:func:`connect`),
* create the schema (:func:`init_db`),
* insert with dedupe-on-``source_hash`` so re-ingesting a file is idempotent
  (:func:`upsert_green`, :func:`upsert_roast`, :func:`upsert_cupping`).

Derived roast metrics are written back with :func:`update_roast_metrics`; the raw
tables stay immutable (enforced by triggers in ``schema.sql``).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from config import DB_PATH

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


# --------------------------------------------------------------------------- #
# Connection / initialisation
# --------------------------------------------------------------------------- #
def connect(db_path: str | Path = DB_PATH) -> sqlite3.Connection:
    """Open a connection with ``Row`` factory and FK enforcement enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path: str | Path = DB_PATH, *, reset: bool = False) -> sqlite3.Connection:
    """Create the schema. With ``reset=True`` the DB file is deleted first.

    Returns an open connection to the (now-initialised) database.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        db_path.unlink()
    conn = connect(db_path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# Generic dedupe-aware insert
# --------------------------------------------------------------------------- #
def _upsert(
    conn: sqlite3.Connection,
    table: str,
    data: Mapping[str, Any],
    id_col: str,
) -> tuple[int, bool]:
    """Insert ``data`` into ``table``; if a row with the same ``source_hash``
    already exists, return its id instead. Returns ``(id, created)``.
    """
    data = {k: v for k, v in data.items() if v is not None or k == "source_hash"}
    source_hash = data.get("source_hash")
    cur = conn.cursor()
    if source_hash is not None:
        row = cur.execute(
            f"SELECT {id_col} FROM {table} WHERE source_hash = ?", (source_hash,)
        ).fetchone()
        if row is not None:
            return int(row[0]), False

    cols = list(data.keys())
    placeholders = ", ".join("?" for _ in cols)
    cur.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
        [data[c] for c in cols],
    )
    return int(cur.lastrowid), True


def upsert_green(conn: sqlite3.Connection, data: Mapping[str, Any]) -> tuple[int, bool]:
    return _upsert(conn, "greens", data, "green_id")


def upsert_roast(conn: sqlite3.Connection, data: Mapping[str, Any]) -> tuple[int, bool]:
    return _upsert(conn, "roasts", data, "roast_id")


def upsert_cupping(conn: sqlite3.Connection, data: Mapping[str, Any]) -> tuple[int, bool]:
    return _upsert(conn, "cuppings", data, "cupping_id")


# --------------------------------------------------------------------------- #
# Curve samples
# --------------------------------------------------------------------------- #
def insert_curve_points(
    conn: sqlite3.Connection,
    roast_id: int,
    points: Sequence[Mapping[str, Any]],
) -> int:
    """Bulk-insert curve samples. ``INSERT OR IGNORE`` respects the
    ``UNIQUE(roast_id, time_s)`` constraint so a re-ingest adds no duplicates.
    Returns the number of rows actually inserted.
    """
    rows = [
        (roast_id, p["time_s"], p.get("bean_temp"), p.get("env_temp"), p.get("ror"))
        for p in points
    ]
    cur = conn.cursor()
    before = conn.total_changes
    cur.executemany(
        "INSERT OR IGNORE INTO roast_curves (roast_id, time_s, bean_temp, env_temp, ror) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    return conn.total_changes - before


def get_curve(conn: sqlite3.Connection, roast_id: int) -> list[sqlite3.Row]:
    """Return a roast's samples ordered by time."""
    return conn.execute(
        "SELECT time_s, bean_temp, env_temp, ror FROM roast_curves "
        "WHERE roast_id = ? ORDER BY time_s",
        (roast_id,),
    ).fetchall()


def update_curve_ror(
    conn: sqlite3.Connection, roast_id: int, ror_by_time: Mapping[float, float]
) -> None:
    """Write the DERIVED ``ror`` column back per sample (raw columns untouched)."""
    conn.executemany(
        "UPDATE roast_curves SET ror = ? WHERE roast_id = ? AND time_s = ?",
        [(ror, roast_id, t) for t, ror in ror_by_time.items()],
    )


# --------------------------------------------------------------------------- #
# Derived roast metrics writeback
# --------------------------------------------------------------------------- #
DERIVED_ROAST_COLUMNS = (
    "turning_point_temp",
    "turning_point_time_s",
    "total_time_s",
    "drying_time_s",
    "maillard_time_s",
    "development_time_s",
    "dtr_pct",
    "dry_end_inferred",
    "ror_crash",
    "ror_crash_severity",
    "ror_flick",
    "ror_flick_severity",
    # event fields may be filled in from an inferred fallback:
    "dry_end_time_s",
    "dry_end_temp",
)


def update_roast_metrics(
    conn: sqlite3.Connection, roast_id: int, metrics: Mapping[str, Any]
) -> None:
    """Update only the DERIVED columns of a roast row from a metrics mapping."""
    cols = [c for c in DERIVED_ROAST_COLUMNS if c in metrics]
    if not cols:
        return
    assignments = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(
        f"UPDATE roasts SET {assignments} WHERE roast_id = ?",
        [metrics[c] for c in cols] + [roast_id],
    )


# --------------------------------------------------------------------------- #
# Queries used by the gate / analysis / dashboard
# --------------------------------------------------------------------------- #
def count_matched_roasts(conn: sqlite3.Connection) -> int:
    """Number of roasts with >= 1 scored cupping -- the Phase 2 gate count."""
    row = conn.execute("SELECT COUNT(*) AS n FROM matched_roasts").fetchone()
    return int(row["n"])


def roast_ids_with_curves(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT roast_id FROM roast_curves ORDER BY roast_id"
    ).fetchall()
    return [int(r["roast_id"]) for r in rows]


def read_sql(conn: sqlite3.Connection, sql: str, params: Iterable[Any] | None = None):
    """Convenience: run a query and return a pandas DataFrame."""
    import pandas as pd  # lazy: keeps this module importable for pure-schema tests

    return pd.read_sql_query(sql, conn, params=list(params) if params else None)
