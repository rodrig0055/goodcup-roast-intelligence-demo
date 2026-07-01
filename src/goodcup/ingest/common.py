"""Shared ingest helpers: content hashing (for idempotent re-import), the
parsed-roast container, and the single code path that stores a parsed roast and
finalises its derived metrics.

Every parser (artisan/cropster/manual) produces :class:`ParsedRoast` objects and
hands them to :func:`store_parsed_roast`, so dedupe and metric computation live in
exactly one place.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

from goodcup.analysis import roast_metrics as rm
from goodcup.db import models


# --------------------------------------------------------------------------- #
# Hashing / normalisation
# --------------------------------------------------------------------------- #
def content_hash(*parts: Any) -> str:
    """Stable SHA-256 over the given parts -- the dedupe key for re-ingestion."""
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def norm_lot(lot_name: str | None) -> str:
    return (lot_name or "").strip().lower()


def green_hash(lot_name: str | None) -> str:
    """Greens dedupe on their lot name so the same lot referenced by a roast log
    and by the green-intake sheet merges into one row."""
    return content_hash("green", norm_lot(lot_name))


# --------------------------------------------------------------------------- #
# Parsed-roast container
# --------------------------------------------------------------------------- #
@dataclass
class ParsedRoast:
    """One roast plus (optionally) its green and curve, as produced by a parser."""

    roast: dict[str, Any]                      # columns for `roasts`
    green: dict[str, Any] = field(default_factory=dict)   # columns for `greens`
    curve: list[dict[str, Any]] = field(default_factory=list)  # time_s/bean_temp/env_temp
    roast_source_hash: Optional[str] = None    # dedupe key for the roast


# --------------------------------------------------------------------------- #
# Storage + metric finalisation (single code path)
# --------------------------------------------------------------------------- #
def store_parsed_roast(conn: sqlite3.Connection, parsed: ParsedRoast) -> dict:
    """Upsert green + roast (deduped), insert the curve if new, then finalise
    derived metrics. Idempotent: re-storing the same roast inserts nothing and
    recomputes nothing. Returns a small result dict for reporting/tests."""
    lot = parsed.green.get("lot_name") or parsed.roast.get("_lot_name")
    green_data = dict(parsed.green)
    green_data.setdefault("lot_name", lot or "Unknown lot")
    green_data["source_hash"] = green_hash(green_data["lot_name"])
    green_id, _ = models.upsert_green(conn, green_data)

    roast_data = {k: v for k, v in parsed.roast.items() if not k.startswith("_")}
    roast_data["green_id"] = green_id
    roast_data["curve_available"] = 1 if parsed.curve else 0
    roast_data["source_hash"] = parsed.roast_source_hash or content_hash(
        "roast", green_id, roast_data.get("roast_ref"), roast_data.get("roast_date"),
        roast_data.get("machine_id"),
    )
    roast_id, created = models.upsert_roast(conn, roast_data)

    n_curve = 0
    if created:
        if parsed.curve:
            n_curve = models.insert_curve_points(conn, roast_id, parsed.curve)
        finalize_metrics(conn, roast_id)
    conn.commit()
    return {
        "green_id": green_id,
        "roast_id": roast_id,
        "created": created,
        "n_curve": n_curve,
    }


def finalize_metrics(conn: sqlite3.Connection, roast_id: int) -> None:
    """(Re)compute derived roast metrics for one roast. With a curve, full metrics
    (TP, phases, DTR, RoR series, crash/flick) are computed and written; without a
    curve, phase/DTR are still derived from any entered event times."""
    row = conn.execute("SELECT * FROM roasts WHERE roast_id = ?", (roast_id,)).fetchone()
    if row is None:
        return
    events = rm.RoastEvents(
        charge_time_s=0.0,
        dry_end_time_s=row["dry_end_time_s"],
        fc_start_time_s=row["fc_start_time_s"],
        fc_end_time_s=row["fc_end_time_s"],
        drop_time_s=row["drop_time_s"],
    )
    curve = models.get_curve(conn, roast_id)
    if curve:
        times = [c["time_s"] for c in curve]
        bt = [c["bean_temp"] for c in curve]
        metrics = rm.compute_metrics(times, bt, events, temp_unit=row["temp_unit"] or "C")
        models.update_roast_metrics(conn, roast_id, metrics.as_derived_dict())
        ror_by_time = {t: (None if r is None else float(r)) for t, r in zip(times, metrics.ror)}
        models.update_curve_ror(conn, roast_id, ror_by_time)
    else:
        models.update_roast_metrics(conn, roast_id, rm.phase_metrics(events))


def resolve_roast_id(conn: sqlite3.Connection, roast_ref: str | None) -> Optional[int]:
    """Look up a roast by its human ``roast_ref`` (used to attach manual cupping rows)."""
    if not roast_ref:
        return None
    row = conn.execute(
        "SELECT roast_id FROM roasts WHERE roast_ref = ? ORDER BY roast_id LIMIT 1",
        (roast_ref,),
    ).fetchone()
    return int(row["roast_id"]) if row else None
