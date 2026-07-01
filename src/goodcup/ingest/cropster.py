"""Parse a Cropster CSV roast export into the schema.

Cropster's real exports vary by plan/version; this parser targets the synthetic
representation in ``seed.synthetic_files.write_cropster_csv`` (documented there):
``# key: value`` metadata lines, then a table
``time_s,bean_temp,env_temp,event`` where the ``event`` column carries
Charge / Dry End / First Crack / First Crack End / Drop on the relevant rows.
Time is re-zeroed at the Charge event. Treat CSV as the baseline; a Cropster API
path is future work (PRD section 8).
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from goodcup.ingest.common import ParsedRoast, content_hash, store_parsed_roast


def _f(v) -> Optional[float]:
    if v is None:
        return None
    v = str(v).strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def parse_cropster_csv(path: str | Path) -> ParsedRoast:
    path = Path(path)
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")

    meta: dict[str, str] = {}
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            body = line[1:].strip()
            if ":" in body:
                k, v = body.split(":", 1)
                meta[k.strip().lower()] = v.strip()
        elif line.strip():
            data_lines.append(line)

    rows = list(csv.DictReader(data_lines))

    charge_time = 0.0
    for r in rows:
        if (r.get("event") or "").strip().lower() == "charge":
            charge_time = _f(r.get("time_s")) or 0.0
            break

    temp_unit = "F" if meta.get("unit", "C").upper().startswith("F") else "C"

    curve: list[dict] = []
    events: dict[str, tuple[Optional[float], Optional[float]]] = {}
    for r in rows:
        t_raw = _f(r.get("time_s"))
        if t_raw is None:
            continue
        t = t_raw - charge_time
        bt, et = _f(r.get("bean_temp")), _f(r.get("env_temp"))
        if t >= 0:
            curve.append({"time_s": t, "bean_temp": bt, "env_temp": et})
        ev = (r.get("event") or "").strip().lower()
        if ev:
            events[ev] = (t, bt)

    def ev(name: str) -> tuple[Optional[float], Optional[float]]:
        return events.get(name, (None, None))

    de, fcs, fce, drop = ev("dry end"), ev("first crack"), ev("first crack end"), ev("drop")
    lot_name = meta.get("green")

    roast = {
        "machine_id": meta.get("machine"),
        "roaster_name": meta.get("roaster"),
        "roast_ref": meta.get("batch"),
        "roast_date": meta.get("date"),
        "temp_unit": temp_unit,
        "charge_temp": ev("charge")[1],
        "dry_end_time_s": de[0],
        "dry_end_temp": de[1],
        "fc_start_time_s": fcs[0],
        "fc_start_temp": fcs[1],
        "fc_end_time_s": fce[0],
        "fc_end_temp": fce[1],
        "drop_time_s": drop[0],
        "drop_temp": drop[1],
        "source_software": "cropster",
        "raw_profile_path": str(path),
        "_lot_name": lot_name,
    }
    return ParsedRoast(
        roast=roast,
        green={"lot_name": lot_name},
        curve=curve,
        roast_source_hash=content_hash("cropster", raw),
    )


def ingest_file(conn, path: str | Path) -> dict:
    return store_parsed_roast(conn, parse_cropster_csv(path))


def ingest_dir(conn, directory: str | Path) -> list[dict]:
    return [ingest_file(conn, p) for p in sorted(Path(directory).glob("*.csv"))]
