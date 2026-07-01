"""Parse Artisan ``.alog`` roast profiles into the schema.

An ``.alog`` is a Python dict literal (Artisan writes it with ``repr``). The
structure below matches common Artisan versions but **field names drift between
versions** -- if real client files arrive, inspect the actual bytes and adjust
(PRD section 0/8). Relevant keys:

* ``mode``      -- 'C' or 'F' (temperature unit; preserved, never converted)
* ``timex``     -- time axis in seconds from *recording* start
* ``temp2``     -- bean temperature (BT) series
* ``temp1``     -- environmental/drum temperature (ET) series
* ``timeindex`` -- indices into ``timex`` for
                   [CHARGE, DRY_END, FC_START, FC_END, SC_START, SC_END, DROP, COOL];
                   0 means "not marked" for every position except CHARGE.

The curve is stored from CHARGE onward with time re-zeroed at charge; event times
are stored as seconds from charge.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from goodcup.ingest.common import ParsedRoast, content_hash, store_parsed_roast


def _load(text: str) -> dict:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return json.loads(text)


def parse_alog(path: str | Path) -> ParsedRoast:
    path = Path(path)
    raw = path.read_bytes()
    d = _load(raw.decode("utf-8", errors="replace"))

    mode = str(d.get("mode", "C")).upper()
    temp_unit = "F" if mode.startswith("F") else "C"

    timex = list(d.get("timex", []))
    temp2 = list(d.get("temp2", []))  # BT
    temp1 = list(d.get("temp1", []))  # ET
    ti = list(d.get("timeindex", []))

    charge_idx = int(ti[0]) if ti else 0
    charge_time = float(timex[charge_idx]) if timex else 0.0

    def ev_time(pos: int):
        if len(ti) > pos and ti[pos] and int(ti[pos]) < len(timex):
            return float(timex[int(ti[pos])]) - charge_time
        return None

    def ev_temp(pos: int):
        if len(ti) > pos and ti[pos] and int(ti[pos]) < len(temp2):
            return float(temp2[int(ti[pos])])
        return None

    drop_time = ev_time(6)

    curve: list[dict] = []
    for i in range(charge_idx, len(timex)):
        t = float(timex[i]) - charge_time
        if drop_time is not None and t > drop_time + 1e-6:
            break  # ignore the cool-down tail after drop
        curve.append(
            {
                "time_s": t,
                "bean_temp": float(temp2[i]) if i < len(temp2) else None,
                "env_temp": float(temp1[i]) if i < len(temp1) else None,
            }
        )

    lot_name = d.get("beans")
    roast = {
        "machine_id": d.get("roastertype"),
        "roaster_name": d.get("operator"),
        "roast_ref": d.get("title"),
        "roast_date": d.get("roastdate"),
        "temp_unit": temp_unit,
        "charge_temp": float(temp2[charge_idx]) if charge_idx < len(temp2) else None,
        "dry_end_time_s": ev_time(1),
        "dry_end_temp": ev_temp(1),
        "fc_start_time_s": ev_time(2),
        "fc_start_temp": ev_temp(2),
        "fc_end_time_s": ev_time(3),
        "fc_end_temp": ev_temp(3),
        "drop_time_s": drop_time,
        "drop_temp": ev_temp(6),
        "source_software": "artisan",
        "raw_profile_path": str(path),
        "_lot_name": lot_name,
    }
    return ParsedRoast(
        roast=roast,
        green={"lot_name": lot_name},
        curve=curve,
        roast_source_hash=content_hash("artisan", raw),
    )


def ingest_file(conn, path: str | Path) -> dict:
    return store_parsed_roast(conn, parse_alog(path))


def ingest_dir(conn, directory: str | Path) -> list[dict]:
    return [ingest_file(conn, p) for p in sorted(Path(directory).glob("*.alog"))]
