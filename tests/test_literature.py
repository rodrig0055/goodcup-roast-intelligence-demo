"""Tests for scholarly-literature retrieval, caching, and offline behaviour.

No live network: ``_http_get`` is monkeypatched with recorded payloads.
"""

from __future__ import annotations

import json

import pytest

from goodcup.db import models
from goodcup.research import literature as L

CROSSREF_PAYLOAD = json.dumps({
    "message": {"items": [{
        "DOI": "10.1234/abc",
        "title": ["Development time ratio and cup score"],
        "author": [{"given": "A", "family": "Roaster"}, {"given": "B", "family": "Cupper"}],
        "issued": {"date-parts": [[2021, 3]]},
        "container-title": ["Journal of Coffee Science"],
        "abstract": "<jats:p>We find DTR <i>associates</i> with score.</jats:p>",
        "URL": "https://doi.org/10.1234/abc",
    }]}
}).encode()


def test_crossref_parsing_normalises_and_strips_markup(monkeypatch):
    monkeypatch.setattr(L, "_http_get", lambda url, timeout=6.0: CROSSREF_PAYLOAD)
    papers = L.search_papers("dtr cup score", source="crossref")
    assert len(papers) == 1
    p = papers[0]
    assert p["title"] == "Development time ratio and cup score"
    assert p["doi"] == "10.1234/abc"
    assert p["year"] == 2021
    assert p["authors"] == "A Roaster, B Cupper"
    assert "<" not in (p["abstract"] or "")           # JATS/HTML tags stripped
    assert p["source_api"] == "crossref"


def test_save_papers_caches_and_dedupes(conn, monkeypatch):
    monkeypatch.setattr(L, "_http_get", lambda url, timeout=6.0: CROSSREF_PAYLOAD)
    papers = L.search_papers("dtr", source="crossref")
    ids1 = L.save_papers(conn, papers, query="dtr")
    ids2 = L.save_papers(conn, papers, query="dtr again")  # same DOI -> same row
    assert ids1 == ids2
    assert len(models.list_references(conn)) == 1


def test_offline_raises_literature_unavailable(monkeypatch):
    def boom(url, timeout=6.0):
        raise L.LiteratureUnavailable("offline")
    monkeypatch.setattr(L, "_http_get", boom)
    with pytest.raises(L.LiteratureUnavailable):
        L.search_papers("anything", source="crossref")


def test_cached_references_survive_when_network_drops(conn, monkeypatch):
    # first, a successful pull caches a paper
    monkeypatch.setattr(L, "_http_get", lambda url, timeout=6.0: CROSSREF_PAYLOAD)
    L.save_papers(conn, L.search_papers("dtr", source="crossref"))
    # then the network drops; the cache is still readable
    monkeypatch.setattr(L, "_http_get", lambda url, timeout=6.0: (_ for _ in ()).throw(L.LiteratureUnavailable("offline")))
    with pytest.raises(L.LiteratureUnavailable):
        L.search_papers("dtr", source="crossref")
    assert len(models.list_references(conn)) == 1


def test_empty_query_returns_no_papers():
    assert L.search_papers("   ", source="crossref") == []
