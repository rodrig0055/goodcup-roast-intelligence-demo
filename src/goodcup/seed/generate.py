"""Synthetic demo-data generator (prototype only -- NOT part of the production path).

This exists so a client can watch the tool behave correctly at every data volume.
It is deterministic (seeded) and, importantly, it *plants known structure* so the
honest-analysis machinery can be seen working in both directions:

* **A real signal** -- Development Time Ratio (``dtr_pct``) is positively associated
  with cup score within the sampled range. ``correlation.py`` should surface it and
  it should survive Benjamini-Hochberg FDR.
* **Null variables** -- ``charge_temp`` / ``turning_point_temp`` have no true effect;
  they should NOT survive FDR. (If they do, the guardrails are broken.)
* **A drifting cupper** -- ``Dee`` scores progressively higher than the panel
  consensus over time, so ``calibration.py`` flags a drift the team could act on.
* **Confounders** -- multiple machines and processes with small offsets, so
  ``correlation.py`` has something real to flag/stratify.
* **Mixed forms** -- sessions alternate SCA-traditional and CVA, so analysis must
  segment by ``form_type``.

Scenarios (sizes in config.SEED_SCENARIOS):
* ``empty``  -> schema only (every "insufficient data" state visible)
* ``sparse`` -> below the Phase 2 gate (exploratory-only; recommender refuses)
* ``full``   -> above the gate (recommender runs)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from config import DB_PATH, RANDOM_SEED, SEED_SCENARIOS
from goodcup.db import models
from goodcup.ingest.common import ParsedRoast, green_hash, store_parsed_roast
from goodcup.seed.synthetic_files import CurveEvents, make_roast_curve

# --------------------------------------------------------------------------- #
# Planted structure (documented on purpose -- this is the demo's whole point)
# --------------------------------------------------------------------------- #
QUALITY_BASE = 84.0
DTR_CENTER = 19.0
DTR_COEF = 0.30          # planted signal: +score per +1 pt DTR (within range)
QUALITY_NOISE = 0.7
CUP_NOISE = 0.5

MACHINES = ["Probat-P12", "Loring-S15", "Giesen-W6"]
MACHINE_EFFECT = {"Probat-P12": 0.3, "Loring-S15": 0.0, "Giesen-W6": -0.4}
ROASTERS = ["Sam", "Mia", "Lena"]

CUPPERS = ["Ana", "Ben", "Cid", "Dee"]
DRIFTER = "Dee"
CUPPER_BIAS = {"Ana": 0.0, "Ben": -0.5, "Cid": 0.35}  # Dee handled via drift

# origin/process archetypes: (country, region, process, varietal, density, moisture,
# water_activity, altitude, screen, process_effect, descriptor pool)
ARCHETYPES = [
    ("Ethiopia", "Yirgacheffe", "washed", "Heirloom", 720, 10.3, 0.53, 1950, 15, 0.2,
     ["jasmine", "bergamot", "lemon", "black tea", "honey", "floral"]),
    ("Ethiopia", "Guji", "natural", "Heirloom", 705, 11.0, 0.58, 2050, 14, -0.1,
     ["blueberry", "strawberry", "cocoa", "winey", "tropical"]),
    ("Colombia", "Huila", "washed", "Pink Bourbon", 735, 10.6, 0.55, 1750, 16, 0.2,
     ["red apple", "caramel", "orange", "floral", "panela", "meyer lemon"]),
    ("Kenya", "Nyeri", "washed", "SL28", 745, 10.1, 0.52, 1800, 17, 0.25,
     ["blackcurrant", "grapefruit", "tomato", "cane sugar", "juicy"]),
    ("Guatemala", "Huehuetenango", "honey", "Caturra", 725, 10.8, 0.56, 1650, 15, 0.0,
     ["milk chocolate", "red grape", "brown sugar", "almond"]),
    ("Brazil", "Cerrado", "natural", "Yellow Bourbon", 690, 11.2, 0.59, 1150, 16, -0.15,
     ["peanut", "milk chocolate", "caramel", "low acidity"]),
    ("Indonesia", "Sumatra", "anaerobic", "Ateng", 700, 11.5, 0.60, 1400, 16, 0.3,
     ["clove", "cedar", "dark chocolate", "herbal", "funky"]),
]


# --------------------------------------------------------------------------- #
# Greens
# --------------------------------------------------------------------------- #
def _make_greens(conn: sqlite3.Connection, n: int, rng: np.random.Generator) -> list[dict]:
    greens = []
    for i in range(n):
        a = ARCHETYPES[i % len(ARCHETYPES)]
        (country, region, process, varietal, dens, moist, wa, alt, screen, peff, descs) = a
        lot = f"{region} {process.title()} L{i + 1:02d}"
        data = {
            "lot_name": lot,
            "origin_country": country,
            "region": region,
            "farm_or_coop": f"{region} Producers",
            "varietal": varietal,
            "process": process,
            "harvest_year": 2025,
            "altitude_masl": float(alt + rng.integers(-100, 100)),
            "density_g_per_l": float(dens + rng.normal(0, 8)),
            "moisture_pct": float(moist + rng.normal(0, 0.3)),
            "water_activity": float(np.clip(wa + rng.normal(0, 0.02), 0.4, 0.7)),
            "screen_size": float(screen + rng.integers(-1, 2)),
            "supplier": rng.choice(["Trabocca", "Cafe Imports", "Sucafina", "Direct"]),
            "arrival_date": "2026-01-05",
            "price_per_kg": float(round(6.5 + rng.normal(1.5, 0.8), 2)),
            "notes": "",
        }
        # use the same dedupe key store_parsed_roast uses, so roasts referencing
        # this lot resolve back to this row instead of creating a duplicate green
        gid, _ = models.upsert_green(conn, {**data, "source_hash": green_hash(data["lot_name"])})
        greens.append({
            "green_id": gid, "process": process, "process_effect": peff,
            "quality": float(rng.normal(0, 0.8)), "descriptors": descs,
            "origin_country": country,
        })
    return greens


# --------------------------------------------------------------------------- #
# Roasts (with curves + the planted DTR signal in the resulting cup score)
# --------------------------------------------------------------------------- #
def _make_roasts(
    conn: sqlite3.Connection,
    greens: list[dict],
    n: int,
    rng: np.random.Generator,
    summary_only_frac: float = 0.08,
) -> list[dict]:
    roasts = []
    for i in range(n):
        green = greens[int(rng.integers(0, len(greens)))]
        machine = MACHINES[int(rng.integers(0, len(MACHINES)))]
        roaster = ROASTERS[int(rng.integers(0, len(ROASTERS)))]

        drop_time = float(np.clip(rng.normal(585, 35), 480, 700))
        target_dtr = float(rng.uniform(14, 24))
        fc_start = drop_time * (1 - target_dtr / 100.0)
        dry_end = fc_start * float(rng.uniform(0.60, 0.70))
        fc_end = min(fc_start + rng.uniform(45, 70), drop_time - 5)
        tp_time = float(rng.uniform(60, 85))
        tp_temp = float(rng.uniform(86, 98))
        charge_temp = float(rng.uniform(195, 208))     # NULL variable (no effect)
        drop_temp = float(rng.normal(210, 3))

        summary_only = rng.random() < summary_only_frac
        parsed_roast = {
            "machine_id": machine,
            "roaster_name": roaster,
            "roast_ref": f"S-{i + 1:03d}",
            "roast_date": f"2026-0{1 + (i % 3)}-{1 + (i % 27):02d}",
            "temp_unit": "C",
            "batch_size_g": float(rng.choice([900, 1000, 1200, 1500])),
            "ambient_temp_c": float(round(rng.uniform(24, 30), 1)),
            "ambient_humidity_pct": float(round(rng.uniform(55, 78), 1)),
            "charge_temp": charge_temp,
            "source_software": "manual" if summary_only else rng.choice(["artisan", "cropster"]),
            "_lot_name": None,
        }

        if summary_only:
            # paper-logged: store event times directly, no curve
            parsed_roast.update({
                "dry_end_time_s": round(dry_end, 1), "fc_start_time_s": round(fc_start, 1),
                "fc_end_time_s": round(fc_end, 1), "drop_time_s": round(drop_time, 1),
                "drop_temp": round(drop_temp, 1),
            })
            parsed = ParsedRoast(
                roast={**parsed_roast, "green_id": green["green_id"]},
                green={}, curve=[], roast_source_hash=f"seed-roast-{i}",
            )
        else:
            times, bt, et = make_roast_curve(
                charge_temp=charge_temp, tp_temp=tp_temp, tp_time=tp_time,
                drop_temp=drop_temp, drop_time=round(drop_time), dt=2.0, rng=rng,
            )
            events = CurveEvents(round(dry_end), round(fc_start), round(fc_end), round(drop_time))
            parsed_roast.update({
                "dry_end_time_s": events.dry_end_time_s, "fc_start_time_s": events.fc_start_time_s,
                "fc_end_time_s": events.fc_end_time_s, "drop_time_s": events.drop_time_s,
                "drop_temp": round(drop_temp, 1),
            })
            curve = [{"time_s": float(t), "bean_temp": float(b), "env_temp": float(e)}
                     for t, b, e in zip(times, bt, et)]
            parsed = ParsedRoast(
                roast={**parsed_roast, "green_id": green["green_id"]},
                green={}, curve=curve, roast_source_hash=f"seed-roast-{i}",
            )

        # green_id already set; store_parsed_roast will re-resolve via lot only if
        # _lot_name given -- here we pass green_id directly, so patch green dict:
        parsed.green = {"lot_name": _lot_of(conn, green["green_id"])}
        res = store_parsed_roast(conn, parsed)

        actual = conn.execute(
            "SELECT dtr_pct FROM roasts WHERE roast_id = ?", (res["roast_id"],)
        ).fetchone()["dtr_pct"]
        quality = (
            QUALITY_BASE
            + DTR_COEF * ((actual if actual is not None else DTR_CENTER) - DTR_CENTER)
            + green["quality"]
            + MACHINE_EFFECT[machine]
            + green["process_effect"]
            + rng.normal(0, QUALITY_NOISE)
        )
        roasts.append({
            "roast_id": res["roast_id"], "green": green, "quality": float(quality),
        })
    return roasts


def _lot_of(conn: sqlite3.Connection, green_id: int) -> str:
    return conn.execute(
        "SELECT lot_name FROM greens WHERE green_id = ?", (green_id,)
    ).fetchone()["lot_name"]


# --------------------------------------------------------------------------- #
# Cuppings (multi-cupper sessions, mixed forms, planted drift)
# --------------------------------------------------------------------------- #
def _score_components(total: float, form: str, rng: np.random.Generator) -> dict:
    """Plausible per-attribute scores for display. Analysis keys off total_score,
    so these need only look right; they are not forced to sum exactly."""
    if form == "cva":
        # CVA affective impression-of-quality, 1-9 scale (higher = better)
        base = float(np.clip(5.5 + (total - QUALITY_BASE) * 0.4, 1, 9))
        j = lambda: float(round(np.clip(base + rng.normal(0, 0.4), 1, 9), 1))
        return {"flavor": j(), "aftertaste": j(), "acidity": j(), "body": j(),
                "balance": j(), "sweetness": j(), "overall": j(),
                "fragrance_aroma": j(), "uniformity": None, "clean_cup": None,
                "defect_points": 0.0}
    # SCA traditional 6-10 scale
    base = float(np.clip(7.5 + (total - QUALITY_BASE) * 0.18, 6, 10))
    j = lambda: float(round(np.clip(base + rng.normal(0, 0.2), 6, 10), 2))
    return {"fragrance_aroma": j(), "flavor": j(), "aftertaste": j(), "acidity": j(),
            "body": j(), "balance": j(), "overall": j(),
            "uniformity": 10.0, "clean_cup": 10.0, "sweetness": 10.0, "defect_points": 0.0}


def _make_cuppings(
    conn: sqlite3.Connection,
    roasts: list[dict],
    rng: np.random.Generator,
    per_session: int = 4,
) -> int:
    n_created = 0
    n_sessions = max(1, (len(roasts) + per_session - 1) // per_session)
    for s in range(n_sessions):
        batch = roasts[s * per_session:(s + 1) * per_session]
        if not batch:
            continue
        form = "sca_traditional" if s % 2 == 0 else "cva"
        session_id = f"SES-{s + 1:03d}"
        # panel: Ana & Ben always; Cid/Dee alternate so Dee cups ~half the sessions
        panel = ["Ana", "Ben", "Dee" if s % 2 == 0 else "Cid"]
        for r in batch:
            for cupper in panel:
                if cupper == DRIFTER:
                    bias = 1.0 + 0.12 * s      # planted upward drift over time
                else:
                    bias = CUPPER_BIAS[cupper]
                total = float(round(r["quality"] + bias + rng.normal(0, CUP_NOISE), 2))
                comps = _score_components(total, form, rng)
                descs = ", ".join(
                    rng.choice(r["green"]["descriptors"],
                               size=min(4, len(r["green"]["descriptors"])), replace=False)
                )
                data = {
                    "roast_id": r["roast_id"], "cupper_name": cupper,
                    "cupping_date": "2026-02-20", "session_id": session_id,
                    "form_type": form, "total_score": total,
                    "descriptors_raw": descs, "notes": "",
                    "source_hash": f"seed-cup-{r['roast_id']}-{cupper}",
                    **comps,
                }
                _, created = models.upsert_cupping(conn, data)
                n_created += int(created)
    conn.commit()
    return n_created


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def generate(scenario: str = "full", db_path: str | Path = DB_PATH, seed: int = RANDOM_SEED) -> dict:
    if scenario not in SEED_SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; choose from {list(SEED_SCENARIOS)}")
    sizes = SEED_SCENARIOS[scenario]
    conn = models.init_db(db_path, reset=True)
    try:
        if sizes["greens"] == 0:
            return _summary(conn, scenario)
        rng = np.random.default_rng(seed)
        greens = _make_greens(conn, sizes["greens"], rng)
        roasts = _make_roasts(conn, greens, sizes["roasts"], rng)
        _make_cuppings(conn, roasts, rng)
        return _summary(conn, scenario)
    finally:
        conn.commit()
        conn.close()


def _summary(conn: sqlite3.Connection, scenario: str) -> dict:
    def count(t):
        return conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]

    matched = models.count_matched_roasts(conn)
    from config import PHASE2_MIN_MATCHED_ROASTS
    return {
        "scenario": scenario,
        "greens": count("greens"),
        "roasts": count("roasts"),
        "cuppings": count("cuppings"),
        "matched_roasts": matched,
        "phase2_gate_met": matched >= PHASE2_MIN_MATCHED_ROASTS,
    }
