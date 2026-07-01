"""Tests for the Gemini provider — offline only (no live network calls).

We verify the degradation contract and the honesty guard on descriptor mapping;
the live generateContent path is exercised manually, not in CI.
"""

from __future__ import annotations

import os

import pytest

from goodcup.ai.gemini import GeminiProvider
from goodcup.ai.grounding import GroundedFacts


@pytest.fixture()
def no_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    # ensure the streamlit-secrets fallback can't supply one either
    monkeypatch.setattr("goodcup.ai.gemini._load_key", lambda: None)
    return GeminiProvider()


def test_degrades_without_a_key_and_never_crashes(no_key):
    assert no_key.available is False
    assert no_key.simulated is False
    facts = GroundedFacts(topic="associations", analysis="scan",
                          summary_rows=[{"variable": "DTR", "r": 0.66, "n": 80}])
    for text in (no_key.answer("q", facts), no_key.narrate(facts),
                 no_key.synthesize_literature("h", [{"title": "P"}], facts)):
        assert isinstance(text, str) and text            # a message, not an exception
    assert "key" in no_key.answer("q", facts).lower()


def test_map_descriptor_returns_none_without_a_key(no_key):
    assert no_key.map_descriptor("meyer lemon", {"lemon": ["Fruity", "Citrus Fruit", "Lemon"]}) == (None, None, None)


def test_literature_synthesis_requires_papers(no_key):
    assert "No papers" in no_key.synthesize_literature("h", [], None)


def test_map_descriptor_rejects_paths_outside_the_wheel(monkeypatch):
    """Even a live reply is guarded: a returned path that isn't a real wheel path
    is rejected, so the model can't invent a category."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    g = GeminiProvider()
    lexicon = {"lemon": ["Fruity", "Citrus Fruit", "Lemon"]}
    monkeypatch.setattr(g, "_generate", lambda prompt, _system=True: "Made Up>Not Real>Nope")
    assert g.map_descriptor("x", lexicon) == (None, None, None)
    monkeypatch.setattr(g, "_generate", lambda prompt, _system=True: "Fruity>Citrus Fruit>Lemon")
    assert g.map_descriptor("meyer lemon", lexicon) == ("Fruity", "Citrus Fruit", "Lemon")
