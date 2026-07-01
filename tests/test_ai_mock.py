"""Tests for the mock AI provider.

The load-bearing guarantee: the provider narrates only numbers present in the
grounded facts, is deterministic, always available, and uses correlational
language. If this ever regresses, an 'AI-native' GoodCup would start overstating
certainty — the exact anti-reference the product forbids.
"""

from __future__ import annotations

import re

import pytest

from goodcup.ai import grounding as G
from goodcup.ai.mock import MockProvider
from goodcup.db import models
from goodcup.seed.generate import generate

#: numbers a template may legitimately use that aren't data (confidence level).
_STRUCTURAL = {"95"}
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


@pytest.fixture()
def full_conn(tmp_path):
    db = tmp_path / "full.db"
    generate("full", db)
    conn = models.connect(db)
    yield conn
    conn.close()


def _fabricated(text: str, facts: G.GroundedFacts) -> set[str]:
    allowed = set(facts.numbers()) | _STRUCTURAL
    return {tok for tok in _NUM.findall(text) if tok not in allowed}


def test_provider_is_available_and_simulated():
    p = MockProvider()
    assert p.available is True
    assert p.simulated is True


def test_answer_invents_no_numbers_across_every_topic(full_conn):
    p = MockProvider()
    for q in ("what drives cup score?", "is any cupper drifting?",
              "which flavors track quality?", "recommend a profile",
              "is this lot consistent?"):
        facts = G.route_question(full_conn, q)
        text = p.answer(q, facts)
        assert _fabricated(text, facts) == set(), f"fabricated numbers for {q!r}: {_fabricated(text, facts)}"


def test_answer_contains_the_key_computed_values(full_conn):
    p = MockProvider()
    facts = G.gather_association_facts(full_conn)
    top = facts.summary_rows[0]
    text = p.answer("what drives score?", facts)
    assert top["variable"] in text
    assert G.fmt(top["r"]) in text            # the effect size is actually shown
    assert G.fmt(top["n"]) in text            # and N


def test_output_is_deterministic(full_conn):
    p = MockProvider()
    facts = G.gather_association_facts(full_conn)
    assert p.answer("q", facts) == p.answer("q", facts)
    assert p.narrate(facts) == p.narrate(facts)


def test_language_is_correlational_not_causal(full_conn):
    p = MockProvider()
    text = p.answer("what drives cup score?", G.gather_association_facts(full_conn)).lower()
    assert "associ" in text
    assert "causes" not in text and "proves" not in text


def test_refusal_is_narrated_not_papered_over():
    p = MockProvider()
    refused = G.GroundedFacts(topic="recommendation", analysis="gated recommender",
                              available=False, refusal="locked until 50 matched roasts exist")
    text = p.answer("recommend something", refused)
    assert "50" in text                       # the real reason is surfaced
    assert _fabricated(text, refused) == set()


def test_literature_synthesis_requires_papers():
    p = MockProvider()
    assert "No papers" in p.synthesize_literature("hypothesis", [], None)


def test_literature_synthesis_grounds_in_association(full_conn):
    p = MockProvider()
    facts = G.gather_association_facts(full_conn)
    papers = [{"title": "DTR and cup quality", "year": 2021}]
    text = p.synthesize_literature("DTR and score", papers, facts)
    assert "DTR and cup quality" in text
    assert _fabricated(text, facts) - {"2021", "1"} == set()  # 2021=year, 1=paper count


def test_map_descriptor_guesses_known_neighbor_or_abstains():
    p = MockProvider()
    lexicon = {"lemon": ["Fruity", "Citrus Fruit", "Lemon"], "cocoa": ["Nutty/Cocoa", "Cocoa", "Chocolate"]}
    assert p.map_descriptor("meyer lemon", lexicon) == ("Fruity", "Citrus Fruit", "Lemon")
    assert p.map_descriptor("zzzz", lexicon) == (None, None, None)
    assert p.map_descriptor("", lexicon) == (None, None, None)
