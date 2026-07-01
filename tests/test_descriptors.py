"""Tests for descriptor -> flavor-wheel mapping and descriptor/score association."""

from __future__ import annotations

from goodcup.analysis import descriptors as D
from goodcup.ai.mock import MockProvider

from conftest import make_cupping, make_green, make_roast


def test_map_term_hits_wheel_and_unknown_terms_are_kept_not_invented():
    assert D.map_term("jasmine") == ("Floral", "Floral", "Jasmine")
    assert D.map_term("milk chocolate") == ("Nutty/Cocoa", "Cocoa", "Chocolate")
    # a term the lexicon does not know maps to all-None (stored, but unmapped)
    assert D.map_term("low acidity") == (None, None, None)


def test_split_terms_normalises_separators_and_case():
    assert D.split_terms("Jasmine, Bergamot / lemon; Honey") == ["jasmine", "bergamot", "lemon", "honey"]
    assert D.split_terms("") == []
    assert D.split_terms(None) == []


def test_rebuild_descriptors_populates_and_is_idempotent(conn):
    g = make_green(conn)
    r = make_roast(conn, g)
    make_cupping(conn, r, session_id="S1", cupper_name="Ana", descriptors_raw="jasmine, lemon, mystery-note")

    n1 = D.rebuild_descriptors(conn)
    n2 = D.rebuild_descriptors(conn)  # rerun must not duplicate
    assert n1 == n2 == 3

    rows = conn.execute("SELECT raw_term, wheel_category_l1 FROM descriptors ORDER BY raw_term").fetchall()
    mapping = {row["raw_term"]: row["wheel_category_l1"] for row in rows}
    assert mapping["jasmine"] == "Floral"
    assert mapping["lemon"] == "Fruity"
    assert mapping["mystery-note"] is None            # unmapped kept, not dropped


def test_ai_provider_maps_unknown_terms_and_flags_them(conn):
    g = make_green(conn)
    r = make_roast(conn, g)
    # "meyer lemon" is not in the lexicon; "lemon" is -> AI should map via token match
    make_cupping(conn, r, session_id="S1", descriptors_raw="meyer lemon, jasmine")

    # without a provider: lexicon maps jasmine, leaves meyer lemon unmapped
    D.rebuild_descriptors(conn)
    src = {row["raw_term"]: row["map_source"]
           for row in conn.execute("SELECT raw_term, map_source FROM descriptors")}
    assert src["jasmine"] == "lexicon"
    assert src["meyer lemon"] is None

    # with the mock provider: meyer lemon gets an AI-mapped row, flagged as 'ai'
    D.rebuild_descriptors(conn, provider=MockProvider())
    rows = {row["raw_term"]: (row["map_source"], row["wheel_category_l3"])
            for row in conn.execute("SELECT raw_term, map_source, wheel_category_l3 FROM descriptors")}
    assert rows["jasmine"][0] == "lexicon"        # lexicon still wins for known terms
    assert rows["meyer lemon"][0] == "ai"         # distinguishable from lexicon
    assert rows["meyer lemon"][1] == "Lemon"      # sensible guess


def test_descriptor_score_association_reports_guardrail_columns(conn):
    # two flavour families, one present only on high-scoring roasts
    g = make_green(conn)
    for i in range(12):
        r = make_roast(conn, g)
        high = i % 2 == 0
        notes = "jasmine, lemon" if high else "cocoa, almond"
        make_cupping(conn, r, session_id=f"S{i}", total_score=86.0 if high else 82.0, descriptors_raw=notes)
    D.rebuild_descriptors(conn)
    assoc = D.descriptor_score_association(conn, min_roasts=3)
    assert not assoc.empty
    for col in ("category", "n", "n_present", "r", "ci_low", "ci_high", "p_raw", "p_fdr", "effect"):
        assert col in assoc.columns
    # Floral appears only on the high roasts -> positive association
    floral = assoc[assoc["category"] == "Floral"].iloc[0]
    assert floral["r"] > 0
