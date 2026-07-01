"""Map free-text tasting notes onto the 2016 WCR/SCA Coffee Taster's Flavor
Wheel and analyse how flavour categories relate to cup score.

The ``descriptors`` table is DERIVED (see schema.sql): it is fully rebuilt from
``cuppings.descriptors_raw`` and is safe to delete. Terms that are not in the
bundled lexicon are still stored (with null wheel categories) so nothing is
silently dropped -- an unmapped term is visible, not invented.

The descriptor -> score association reuses the SAME guardrail machinery as
``analysis/correlation.py`` (effect size first, bootstrap/Fisher 95% CI, BH-FDR,
small-sample flag), and is phrased strictly as association, never cause.
"""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
from scipy import stats

from config import BOOTSTRAP_MAX_N, FLAVOR_WHEEL_PATH, SMALL_SAMPLE_WARN_N
from goodcup.analysis.correlation import (
    _bootstrap_ci,
    _fisher_ci,
    benjamini_hochberg,
    effect_label,
)
from goodcup.db import models


@lru_cache(maxsize=1)
def load_lexicon() -> dict[str, list]:
    """Return the raw-term -> [L1, L2, L3] map from the bundled flavor wheel."""
    data = json.loads(FLAVOR_WHEEL_PATH.read_text(encoding="utf-8"))
    return data["lexicon"]


def split_terms(raw: str | None) -> list[str]:
    """Split a free-text descriptor string into normalised terms."""
    if not raw:
        return []
    parts = raw.replace(";", ",").replace("/", ",").split(",")
    return [p.strip().lower() for p in parts if p.strip()]


def map_term(term: str) -> tuple[str | None, str | None, str | None]:
    """Map one normalised term onto (L1, L2, L3); (None, None, None) if unknown."""
    hit = load_lexicon().get(term)
    if hit is None:
        return (None, None, None)
    l1, l2, l3 = (hit + [None, None, None])[:3]
    return (l1, l2, l3)


def rebuild_descriptors(conn, provider=None) -> int:
    """Rebuild the ``descriptors`` table from every cupping's raw notes.

    Terms are first mapped by the deterministic bundled lexicon (``map_source =
    'lexicon'``). When a ``provider`` is given, terms the lexicon can't place are
    passed to ``provider.map_descriptor(term, lexicon)`` for a best-effort guess
    (``map_source = 'ai'``); the guess is cached so it isn't recomputed per row.
    Unmapped terms are kept with ``map_source = NULL`` — nothing is silently
    dropped, and AI guesses are always distinguishable from lexicon mappings.

    Returns the number of descriptor rows written. Idempotent: clears first.
    """
    conn.execute("DELETE FROM descriptors")
    rows = conn.execute(
        "SELECT cupping_id, descriptors_raw FROM cuppings WHERE descriptors_raw IS NOT NULL AND descriptors_raw != ''"
    ).fetchall()
    lexicon = load_lexicon()
    ai_cache: dict[str, tuple] = {}
    payload = []
    for cupping_id, raw in rows:
        for term in split_terms(raw):
            l1, l2, l3 = map_term(term)
            source = "lexicon" if l1 is not None else None
            if l1 is None and provider is not None:
                if term not in ai_cache:
                    ai_cache[term] = provider.map_descriptor(term, lexicon)
                gl1, gl2, gl3 = ai_cache[term]
                if gl1 is not None:
                    l1, l2, l3, source = gl1, gl2, gl3, "ai"
            payload.append((cupping_id, term, l1, l2, l3, source))
    conn.executemany(
        "INSERT INTO descriptors (cupping_id, raw_term, wheel_category_l1, wheel_category_l2, wheel_category_l3, map_source) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        payload,
    )
    conn.commit()
    return len(payload)


def descriptor_frequency(conn, by: str = "origin_country"):
    """Count mapped flavour categories (L1) broken down by a green/roast dimension.

    ``by`` is one of ``origin_country``, ``process``. Returns a tidy DataFrame
    with columns [<by>, wheel_category_l1, n]. Unmapped terms are excluded from
    the frequency view (they carry no wheel category) but remain in the table.
    """
    if by not in {"origin_country", "process"}:
        raise ValueError("by must be 'origin_country' or 'process'")
    return models.read_sql(
        conn,
        f"""
        SELECT g.{by} AS {by}, d.wheel_category_l1, COUNT(*) AS n
        FROM descriptors d
        JOIN cuppings c ON c.cupping_id = d.cupping_id
        JOIN roasts r   ON r.roast_id = c.roast_id
        JOIN greens g   ON g.green_id = r.green_id
        WHERE d.wheel_category_l1 IS NOT NULL
        GROUP BY g.{by}, d.wheel_category_l1
        ORDER BY {by}, n DESC
        """,
    )


def descriptor_score_association(conn, min_roasts: int = 5):
    """Associate presence of each flavour category (L1) with roast cup score.

    Roast-level, robust to per-cupper variation: a roast is tagged with a
    category if ANY of its cuppings mentioned a term in that category. We then
    correlate that 0/1 indicator with the roast's mean cup score (point-biserial
    = Pearson r on a binary variable), under the standard guardrails.

    Returns a DataFrame ranked by |effect size|, with columns
    [category, n, n_present, r, ci_low, ci_high, p_raw, p_fdr, effect, small_sample].
    """
    import pandas as pd

    roast_cat = models.read_sql(
        conn,
        """
        SELECT DISTINCT r.roast_id, d.wheel_category_l1 AS category
        FROM descriptors d
        JOIN cuppings c ON c.cupping_id = d.cupping_id
        JOIN roasts r   ON r.roast_id = c.roast_id
        WHERE d.wheel_category_l1 IS NOT NULL
        """,
    )
    scores = models.read_sql(
        conn, "SELECT roast_id, mean_total_score FROM matched_roasts WHERE mean_total_score IS NOT NULL"
    )
    if roast_cat.empty or scores.empty:
        return pd.DataFrame(columns=["category", "n", "n_present", "r", "ci_low", "ci_high", "p_raw", "p_fdr", "effect", "small_sample"])

    y_by_roast = scores.set_index("roast_id")["mean_total_score"]
    n_total = len(y_by_roast)
    present = roast_cat.groupby("category")["roast_id"].apply(set)

    raw_rows = []
    for category, roast_ids in present.items():
        n_present = len(roast_ids & set(y_by_roast.index))
        # need variation in the indicator to correlate at all
        if n_present < min_roasts or (n_total - n_present) < min_roasts:
            continue
        indicator = y_by_roast.index.isin(roast_ids).astype(float)
        y = y_by_roast.to_numpy(float)
        if np.std(indicator) == 0 or np.std(y) == 0:
            continue
        r, p = stats.pearsonr(indicator, y)
        if n_total <= BOOTSTRAP_MAX_N:
            lo, hi = _bootstrap_ci(indicator, y)
        else:
            lo, hi = _fisher_ci(r, n_total)
        raw_rows.append({
            "category": category, "n": n_total, "n_present": n_present,
            "r": float(r), "ci_low": lo, "ci_high": hi, "p_raw": float(p),
            "effect": effect_label(r), "small_sample": n_total < SMALL_SAMPLE_WARN_N,
        })

    adj = benjamini_hochberg([row["p_raw"] for row in raw_rows])
    for row, a in zip(raw_rows, adj):
        row["p_fdr"] = float(a)
    frame = pd.DataFrame(raw_rows)
    if not frame.empty:
        frame = frame.reindex(frame["r"].abs().sort_values(ascending=False).index).reset_index(drop=True)
    return frame
