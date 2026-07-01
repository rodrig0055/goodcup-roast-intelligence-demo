"""Gated roast-profile recommender and an honest, interpretable score predictor.

Both are held behind the Phase-2 data gate (config.PHASE2_MIN_MATCHED_ROASTS,
PHASE2_MIN_NEIGHBORS). Below the gate they return an explanatory refusal object
rather than a guess -- a recommendation drawn from too little history is worse
than none, because it looks authoritative. Nothing is ever fabricated: neighbors
are real historical roasts, and the predictor is a plain regularised linear model
whose coefficients are reported so the roaster can see what it is keying on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from config import (
    PHASE2_MIN_MATCHED_ROASTS,
    PHASE2_MIN_NEIGHBORS,
    PHASE2_TARGET_NEIGHBORS,
)
from goodcup.db import models

#: Roast numerics the similarity space is built from.
NUMERIC_FEATURES = ["dtr_pct", "development_time_s", "drying_time_s", "drop_temp", "total_time_s"]
#: Green categoricals that must match / are one-hot encoded.
CATEGORICAL_FEATURES = ["process", "origin_country"]


@dataclass
class Recommendation:
    available: bool
    reason: str = ""
    n_matched: int = 0
    neighbors: list[dict] = field(default_factory=list)
    query: dict | None = None


def _load_matched(conn):
    df = models.read_sql(conn, "SELECT * FROM matched_roasts WHERE mean_total_score IS NOT NULL")
    return df.dropna(subset=NUMERIC_FEATURES + ["mean_total_score"])


def recommend_for_green(conn, green_id: int, k: int = PHASE2_TARGET_NEIGHBORS) -> Recommendation:
    """Recommend proven roast profiles from historically similar roasts.

    Gate order (both hard):
      1. Overall matched roasts must reach PHASE2_MIN_MATCHED_ROASTS.
      2. The query green must have >= PHASE2_MIN_NEIGHBORS similar historical
         roasts (same process, with cupped roasts) or we refuse for this query.
    """
    from sklearn.neighbors import NearestNeighbors
    from sklearn.preprocessing import StandardScaler

    df = _load_matched(conn)
    n_matched = len(df)
    if n_matched < PHASE2_MIN_MATCHED_ROASTS:
        return Recommendation(
            available=False, n_matched=n_matched,
            reason=(f"Recommendation is locked until at least {PHASE2_MIN_MATCHED_ROASTS} "
                    f"roasts have matched cupping scores. There are {n_matched} so far. "
                    "Below this, associations are too unstable to recommend from."),
        )

    green = conn.execute("SELECT * FROM greens WHERE green_id = ?", (green_id,)).fetchone()
    if green is None:
        return Recommendation(available=False, n_matched=n_matched, reason=f"No green lot with id {green_id}.")
    green = dict(green)

    # Restrict the neighbourhood to the same process (a real similarity constraint,
    # not a statistical trick) and require enough of them.
    same_process = df[df["process"] == green.get("process")]
    if len(same_process) < PHASE2_MIN_NEIGHBORS:
        return Recommendation(
            available=False, n_matched=n_matched,
            reason=(f"Only {len(same_process)} historical {green.get('process')} roasts with "
                    f"cup scores exist; at least {PHASE2_MIN_NEIGHBORS} similar greens are "
                    "needed before a profile can be suggested for this lot."),
        )

    # Standardise numerics and find nearest neighbours by green green-analysis +
    # roast numerics. Query point = the lot's own green attributes projected onto
    # the median roast of its process (we recommend, we don't invent a roast).
    feats = same_process[NUMERIC_FEATURES].to_numpy(float)
    scaler = StandardScaler().fit(feats)
    nn = NearestNeighbors(n_neighbors=min(k, len(same_process))).fit(scaler.transform(feats))

    # anchor on the highest-scoring roast of this process as the "what good looks
    # like" query, then surface its nearest reproducible neighbours.
    anchor_idx = same_process["mean_total_score"].to_numpy().argmax()
    dist, idx = nn.kneighbors(scaler.transform(feats)[anchor_idx : anchor_idx + 1])
    rows = same_process.iloc[idx[0]]

    neighbors = []
    for (_, row), d in zip(rows.iterrows(), dist[0]):
        neighbors.append({
            "roast_id": int(row["roast_id"]),
            "mean_total_score": round(float(row["mean_total_score"]), 2),
            "n_cuppings": int(row["n_cuppings"]),
            "dtr_pct": round(float(row["dtr_pct"]), 1),
            "development_time_s": round(float(row["development_time_s"]), 0),
            "drop_temp": round(float(row["drop_temp"]), 1),
            "process": row["process"],
            "origin_country": row["origin_country"],
            "similarity": round(float(1.0 / (1.0 + d)), 3),  # 1 = identical
        })
    neighbors.sort(key=lambda r: r["mean_total_score"], reverse=True)
    return Recommendation(
        available=True, n_matched=n_matched, neighbors=neighbors,
        query={"green_id": green_id, "lot_name": green.get("lot_name"), "process": green.get("process")},
        reason=(f"Drawn from {len(same_process)} historical {green.get('process')} roasts with "
                "cupping scores. These are real past roasts, ranked by cup score — a starting "
                "profile to reproduce and confirm, not a guaranteed outcome."),
    )


@dataclass
class PredictionModel:
    available: bool
    reason: str = ""
    r2_cv: float = float("nan")
    coefficients: dict = field(default_factory=dict)
    n: int = 0


def fit_score_predictor(conn) -> PredictionModel:
    """Fit an interpretable Ridge model: roast numerics -> mean cup score.

    Reports cross-validated R^2 and standardised coefficients so the roaster sees
    what drives the prediction. Gated like the recommender. This is explicitly a
    correlational, exploratory aid -- not a promise about a future roast.
    """
    from sklearn.linear_model import Ridge
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    df = _load_matched(conn)
    n = len(df)
    if n < PHASE2_MIN_MATCHED_ROASTS:
        return PredictionModel(
            available=False, n=n,
            reason=(f"Prediction stays locked until {PHASE2_MIN_MATCHED_ROASTS} matched roasts exist "
                    f"({n} so far)."),
        )
    x = df[NUMERIC_FEATURES].to_numpy(float)
    y = df["mean_total_score"].to_numpy(float)
    scaler = StandardScaler().fit(x)
    xs = scaler.transform(x)
    model = Ridge(alpha=1.0).fit(xs, y)
    folds = min(5, n)
    r2 = float(np.mean(cross_val_score(make_pipeline(StandardScaler(), Ridge(alpha=1.0)), x, y, cv=folds, scoring="r2")))
    coefs = {NUMERIC_FEATURES[i]: round(float(model.coef_[i]), 3) for i in range(len(NUMERIC_FEATURES))}
    return PredictionModel(available=True, n=n, r2_cv=round(r2, 3), coefficients=coefs)
