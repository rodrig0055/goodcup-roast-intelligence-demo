"""Provider-agnostic grounding: compute the real numbers an AI answer may cite.

This module is the honesty boundary. It reuses the existing analysis layer
(correlation, calibration, lot history, descriptors, gated recommendation) to
produce plain-data "fact" dicts. Providers (mock now, Claude later) receive these
facts and may only narrate them -- they never see raw tables and must not emit a
number that isn't already here. The Phase-2 recommendation gate is carried through
verbatim: a below-gate question yields a refusal fact, not a fabricated answer.

Everything here is pure and offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from goodcup.analysis.calibration import calibration_report
from goodcup.analysis.correlation import correlation_report
from goodcup.analysis.descriptors import descriptor_score_association
from goodcup.analysis.lot_history import repeatability_summary
from goodcup.db import models
from goodcup.recommend.similarity import recommend_for_green


@dataclass
class GroundedFacts:
    """A structured, numbers-included answer to one kind of question."""

    topic: str                      # associations | calibration | repeatability | descriptors | recommendation
    analysis: str                   # human-readable name of the analysis that answered
    summary_rows: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    available: bool = True          # False => gated/insufficient data; narrate the refusal, don't invent
    refusal: str = ""

    def numbers(self) -> list[str]:
        """Every numeric token that a provider is allowed to reproduce.

        Includes the row values (formatted to display precision) AND any numbers
        already present in the grounded ``refusal`` / ``notes`` strings — those come
        from the analysis layer (e.g. a gate reason like "50 matched roasts"), so
        echoing them is grounding, not fabrication. Used by the mock templates and
        by tests to prove nothing is invented.
        """
        import re

        out: list[str] = []
        for row in self.summary_rows:
            for v in row.values():
                if isinstance(v, bool) or v is None:
                    continue
                if isinstance(v, (int, float)) and not (isinstance(v, float) and np.isnan(v)):
                    out.append(fmt(v))
        for text in [self.refusal, self.analysis, *self.notes]:
            out.extend(re.findall(r"-?\d+(?:\.\d+)?", text or ""))
        return out


def fmt(v: float | int) -> str:
    """Canonical display string for a number. Providers MUST interpolate numbers
    through this so their output is byte-identical to :meth:`GroundedFacts.numbers`
    — that is what makes the "no fabricated numbers" guarantee checkable."""
    if isinstance(v, int):
        return str(v)
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.2f}"


# --------------------------------------------------------------------------- #
# Fact gatherers
# --------------------------------------------------------------------------- #
def gather_association_facts(conn, top: int = 4) -> GroundedFacts:
    df = correlation_report(conn, stratify=False).overall.to_frame()
    df = df.dropna(subset=["r"]).head(top)
    rows = [
        {
            "variable": r.label, "n": int(r.n), "r": round(float(r.r), 2),
            "ci_low": round(float(r.ci_low), 2), "ci_high": round(float(r.ci_high), 2),
            "p_fdr": round(float(r.p_fdr), 3), "effect": r.effect,
        }
        for r in df.itertuples()
    ]
    return GroundedFacts(
        topic="associations", analysis="guarded correlation scan", summary_rows=rows,
        notes=["Correlational only. Mixed machines, origins, and processes can confound single-variable associations."],
    )


def gather_calibration_facts(conn) -> GroundedFacts:
    status, _ = calibration_report(conn)
    if status.empty:
        return GroundedFacts(topic="calibration", analysis="cupper calibration", available=False,
                             refusal="No cupping data with named cuppers is available yet.")
    rows = [
        {
            "cupper": r.cupper, "n": int(r.n), "mean_deviation": round(float(r.mean_deviation), 2),
            "ci_low": round(float(r.ci_low), 2), "ci_high": round(float(r.ci_high), 2),
            "status": r.status,
        }
        for r in status.itertuples()
    ]
    return GroundedFacts(
        topic="calibration", analysis="cupper calibration", summary_rows=rows,
        notes=["A review flag needs a practically meaningful mean deviation and a 95% CI excluding zero."],
    )


def gather_repeatability_facts(conn, green_id: int) -> GroundedFacts:
    history = models.read_sql(
        conn,
        """
        SELECT r.roast_id, r.curve_available, r.dtr_pct, r.drop_temp, r.total_time_s,
               m.mean_total_score
        FROM roasts r LEFT JOIN matched_roasts m ON m.roast_id = r.roast_id
        WHERE r.green_id = ?
        """,
        [green_id],
    )
    lot = conn.execute("SELECT lot_name FROM greens WHERE green_id = ?", (green_id,)).fetchone()
    rep = repeatability_summary(history)
    row = {"n_roasts": int(rep["n_roasts"])}
    for k in ("score_sd", "dtr_sd", "drop_temp_sd", "total_time_sd"):
        if rep.get(k) is not None:
            row[k] = round(float(rep[k]), 2)
    return GroundedFacts(
        topic="repeatability", analysis=f"lot repeatability for {lot['lot_name'] if lot else green_id}",
        summary_rows=[row], notes=[rep["status"], "Spread describes repeatability, not quality."],
    )


def gather_descriptor_facts(conn, top: int = 4) -> GroundedFacts:
    df = descriptor_score_association(conn)
    if df.empty:
        return GroundedFacts(topic="descriptors", analysis="descriptor / score association", available=False,
                             refusal="Not enough descriptor variety yet to test flavor associations.")
    df = df.head(top)
    rows = [
        {
            "flavor_family": r.category, "n": int(r.n), "n_present": int(r.n_present),
            "r": round(float(r.r), 2), "ci_low": round(float(r.ci_low), 2),
            "ci_high": round(float(r.ci_high), 2), "p_fdr": round(float(r.p_fdr), 3),
        }
        for r in df.itertuples()
    ]
    return GroundedFacts(
        topic="descriptors", analysis="descriptor / score association", summary_rows=rows,
        notes=["A flavor family being present is correlated with score, not shown to cause it."],
    )


def gather_recommendation_facts(conn, green_id: int) -> GroundedFacts:
    """Carry the Phase-2 gate through UNCHANGED. Below the gate this returns a
    refusal fact; the provider narrates the refusal and cannot unlock anything."""
    rec = recommend_for_green(conn, green_id)
    if not rec.available:
        return GroundedFacts(topic="recommendation", analysis="gated recommender",
                             available=False, refusal=rec.reason)
    rows = [
        {
            "cup_score": nb["mean_total_score"], "dtr_pct": nb["dtr_pct"],
            "drop_temp": nb["drop_temp"], "n_cuppings": nb["n_cuppings"],
            "similarity": nb["similarity"],
        }
        for nb in rec.neighbors[:5]
    ]
    return GroundedFacts(
        topic="recommendation", analysis="gated recommender", summary_rows=rows,
        notes=[rec.reason],
    )


# --------------------------------------------------------------------------- #
# Question router
# --------------------------------------------------------------------------- #
_KEYWORDS = {
    "calibration": ("cupper", "calibrat", "drift", "panel", "ana", "ben", "cid", "dee"),
    "recommendation": ("recommend", "suggest", "which profile", "best profile", "what roast", "should i roast"),
    "descriptors": ("flavor", "flavour", "descriptor", "tasting", "note", "fruity", "floral", "cocoa"),
    "repeatability": ("repeat", "consistent", "reproduc", "spread", "stable", "lot history"),
    "associations": ("associat", "correlat", "drive", "dtr", "development", "score", "predict", "relationship"),
}


def route_question(conn, question: str, green_id: int | None = None) -> GroundedFacts:
    """Map a natural-language question to the analysis that can answer it,
    gather the real facts, and return them. Defaults to the association scan."""
    q = (question or "").lower()

    def hit(topic: str) -> bool:
        return any(k in q for k in _KEYWORDS[topic])

    # order matters: more specific topics before the general association fallback
    if hit("calibration"):
        return gather_calibration_facts(conn)
    if hit("recommendation"):
        gid = green_id if green_id is not None else _default_green(conn)
        if gid is None:
            return GroundedFacts(topic="recommendation", analysis="gated recommender",
                                 available=False, refusal="No green lot is available to recommend for.")
        return gather_recommendation_facts(conn, gid)
    if hit("descriptors"):
        return gather_descriptor_facts(conn)
    if hit("repeatability"):
        gid = green_id if green_id is not None else _default_green(conn)
        if gid is None:
            return GroundedFacts(topic="repeatability", analysis="lot repeatability",
                                 available=False, refusal="No green lot is available.")
        return gather_repeatability_facts(conn, gid)
    return gather_association_facts(conn)


def _default_green(conn) -> int | None:
    row = conn.execute("SELECT green_id FROM greens ORDER BY green_id LIMIT 1").fetchone()
    return int(row[0]) if row else None
