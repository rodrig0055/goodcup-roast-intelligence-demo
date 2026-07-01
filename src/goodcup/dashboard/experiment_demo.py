"""Pure helpers for the interactive Experiment Lab demo."""

from __future__ import annotations

import math
from statistics import mean, pstdev


BLIND_PROFILE_MAP = {
    "314": "Control · 18.2% DTR",
    "728": "Treatment A · 20.0% DTR",
    "561": "Treatment B · 21.7% DTR",
}

DEFAULT_CUP_SCORES = {
    "314": [84.50, 84.25, 84.50],
    "728": [85.50, 85.25, 85.75],
    "561": [84.75, 85.00, 84.50],
}


def evaluate_blind_results(scores: dict[str, list[float]]) -> dict:
    """Rank blind-code means and return a cautious prototype decision."""
    if set(scores) != set(BLIND_PROFILE_MAP):
        raise ValueError("Scores must contain every blind code exactly once")
    summaries = []
    for code, values in scores.items():
        if len(values) < 2:
            raise ValueError("Each profile needs at least two replicated cups")
        if any(v < 0 or v > 100 for v in values):
            raise ValueError("Cup scores must be between 0 and 100")
        summaries.append({
            "blind_code": code,
            "profile": BLIND_PROFILE_MAP[code],
            "n": len(values),
            "mean_score": mean(values),
            "spread": pstdev(values),
        })
    summaries.sort(key=lambda row: row["mean_score"], reverse=True)
    margin = summaries[0]["mean_score"] - summaries[1]["mean_score"]
    if margin < 0.5:
        decision = "No clear leader. Repeat the blind comparison before changing production practice."
    else:
        decision = f"Advance {summaries[0]['profile']} to a confirmation roast. Do not generalize from this single trial."
    return {
        "winner": summaries[0],
        "runner_up": summaries[1],
        "margin": margin,
        "ranking": summaries,
        "decision": decision,
    }


def cups_needed(delta: float, spread: float, power: float = 0.80, alpha: float = 0.05) -> int:
    """Replicated cups **per profile** needed to detect a score difference.

    A two-sided, two-sample power calculation using the normal approximation:
    ``n = 2 * ((z_alpha/2 + z_beta) * sd / delta) ** 2`` per group. This tells a
    lab whether a planned blind comparison is powered to see the difference it
    cares about, so an under-powered trial is not mistaken for "no effect".

    ``delta`` is the smallest score difference worth detecting; ``spread`` is the
    within-profile SD (use the observed cup spread). Returns cups per profile
    (>= 2). Raises on non-positive inputs.
    """
    if delta <= 0 or spread <= 0:
        raise ValueError("delta and spread must be positive")
    # inverse-normal via the rational approximation is overkill; use fixed z for
    # the common (0.05, 0.80) case and a small table otherwise.
    z_alpha = {0.05: 1.959964, 0.10: 1.644854, 0.01: 2.575829}.get(round(alpha, 2), 1.959964)
    z_beta = {0.80: 0.841621, 0.90: 1.281552, 0.95: 1.644854}.get(round(power, 2), 0.841621)
    n = 2 * ((z_alpha + z_beta) * spread / delta) ** 2
    return max(2, math.ceil(n))
