"""Deterministic, fully-offline mock AI provider.

Produces templated, plainly-written, strictly correlational narration that
interpolates ONLY the real numbers carried in the grounded facts. It is
deterministic (no randomness, no clock) so tests are stable, and it never emits a
number that isn't in the facts -- the same honesty contract a real model must
meet. The UI badges every response "Simulated AI (mock)".
"""

from __future__ import annotations

from goodcup.ai.grounding import GroundedFacts, fmt
from goodcup.ai.provider import AIProvider


class MockProvider(AIProvider):
    name = "Mock (offline)"
    available = True
    simulated = True

    # ----------------------------------------------------------------- #
    def answer(self, question: str, facts: GroundedFacts) -> str:
        if not facts.available:
            return (
                f"I can't answer that from the current data. {facts.refusal} "
                "This limit is deliberate: an answer drawn from too little evidence would mislead."
            )
        body = self._describe(facts)
        note = f" {facts.notes[0]}" if facts.notes else ""
        return f"Based on the {facts.analysis}: {body}{note}"

    def narrate(self, facts: GroundedFacts) -> str:
        if not facts.available:
            return facts.refusal
        return self._describe(facts)

    def synthesize_literature(self, hypothesis, papers, association) -> str:
        if not papers:
            return (
                "No papers are cached for this hypothesis yet. Search the literature panel "
                "first, then synthesize — I only summarize sources actually retrieved."
            )
        titles = "; ".join(p.get("title", "untitled") for p in papers[:3] if p.get("title"))
        n = len(papers)
        lead = f"Across {fmt(n)} cached paper{'s' if n != 1 else ''} ({titles})"
        if association and association.available and association.summary_rows:
            top = association.summary_rows[0]
            tie = (
                f" Your own data shows {top['variable']} associated with cup score at "
                f"r = {fmt(top['r'])}, 95% CI {fmt(top['ci_low'])} to {fmt(top['ci_high'])}, N = {fmt(top['n'])}."
            )
        else:
            tie = ""
        return (
            f"{lead}, the published work is treated as external evidence about “{hypothesis}”, "
            f"not proof for this roastery.{tie} Read the abstracts before acting; a test roast "
            "on your own greens is still the deciding step."
        )

    def map_descriptor(self, term: str, lexicon: dict[str, list]):
        """Deterministic heuristic guess: find the known lexicon term most similar
        to ``term`` (substring or shared salient token) and return its (L1, L2, L3).
        Returns all-None when nothing is close. A labeled guess, not a model call."""
        t = (term or "").lower().strip()
        if not t:
            return (None, None, None)
        # deterministic scan in sorted order so ties resolve the same way every run
        for known in sorted(lexicon):
            if known and (known in t or t in known or _shares_token(t, known)):
                triple = (lexicon[known] + [None, None, None])[:3]
                return (triple[0], triple[1], triple[2])
        return (None, None, None)

    # ----------------------------------------------------------------- #
    def _describe(self, facts: GroundedFacts) -> str:
        rows = facts.summary_rows
        if not rows:
            return "no rows were returned."
        if facts.topic == "associations":
            r = rows[0]
            p_phrase = "FDR-adjusted p rounds to 0 (highly significant)" if fmt(r["p_fdr"]) == "0" else f"FDR-adjusted p = {fmt(r['p_fdr'])}"
            lead = (
                f"{r['variable']} shows the strongest association with cup score — "
                f"r = {fmt(r['r'])} ({r['effect']}), 95% CI {fmt(r['ci_low'])} to {fmt(r['ci_high'])}, "
                f"N = {fmt(r['n'])}, {p_phrase}."
            )
            if len(rows) > 1:
                others = ", ".join(f"{x['variable']} (r = {fmt(x['r'])})" for x in rows[1:3])
                lead += f" Next: {others}."
            return lead + " Treat these as test-roast hypotheses, not conclusions."
        if facts.topic == "calibration":
            flagged = [r for r in rows if r["status"] == "Review"]
            if flagged:
                r = flagged[0]
                return (
                    f"{r['cupper']} is flagged for review: mean deviation {fmt(r['mean_deviation'])} "
                    f"(95% CI {fmt(r['ci_low'])} to {fmt(r['ci_high'])}, N = {fmt(r['n'])}). The others sit inside the panel consensus."
                )
            return "No cupper is flagged; every panelist's 95% CI includes zero deviation from consensus."
        if facts.topic == "descriptors":
            r = rows[0]
            p_phrase = "FDR p rounds to 0" if fmt(r["p_fdr"]) == "0" else f"FDR p = {fmt(r['p_fdr'])}"
            return (
                f"{r['flavor_family']} shows the largest flavor-to-score association "
                f"(r = {fmt(r['r'])}, 95% CI {fmt(r['ci_low'])} to {fmt(r['ci_high'])}, "
                f"present in {fmt(r['n_present'])} of {fmt(r['n'])} roasts, {p_phrase})."
            )
        if facts.topic == "repeatability":
            r = rows[0]
            sd = r.get("score_sd")
            piece = f" Cup-score spread is {fmt(sd)} points." if sd is not None else ""
            return f"This lot has {fmt(r['n_roasts'])} roasts.{piece}"
        if facts.topic == "recommendation":
            r = rows[0]
            return (
                f"The best-scoring similar roast reached {fmt(r['cup_score'])} at DTR {fmt(r['dtr_pct'])}% "
                f"and drop {fmt(r['drop_temp'])}°C (similarity {fmt(r['similarity'])}). Reproduce and confirm — one roast is not proof."
            )
        return "; ".join(str(v) for v in rows[0].values())


def _shares_token(a: str, b: str) -> bool:
    ta = {w for w in a.replace("-", " ").split() if len(w) > 3}
    tb = {w for w in b.replace("-", " ").split() if len(w) > 3}
    return bool(ta & tb)
