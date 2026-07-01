"""Pull published scientific papers from free, no-key scholarly APIs and cache
them into the local store, linked to the experiments they inform.

Sources: Crossref, Semantic Scholar, and arXiv. Only ``_http_get`` touches the
network -- everything else (parsing, saving, linking) is pure and offline, which
keeps the product local-first: the online pull is one clearly-separated step, and
once a paper is cached it is available and citable offline.

Network failures raise :class:`LiteratureUnavailable` rather than crashing the
caller, so the dashboard can fall back to already-cached references.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import re
from urllib.error import URLError
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from config import CONTACT_EMAIL
from goodcup.db import models

CROSSREF_URL = "https://api.crossref.org/works"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_URL = "http://export.arxiv.org/api/query"

SOURCES = ("crossref", "semantic_scholar", "arxiv")
_TAG_RE = re.compile(r"<[^>]+>")


class LiteratureUnavailable(RuntimeError):
    """Raised when a scholarly API cannot be reached (offline / timeout / HTTP error)."""


@dataclass
class Paper:
    title: str
    doi: str | None = None
    authors: str | None = None
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    url: str | None = None
    source_api: str | None = None

    def source_hash(self) -> str:
        if self.doi:
            return f"doi:{self.doi.strip().lower()}"
        return "title:" + re.sub(r"\s+", " ", (self.title or "").strip().lower())


# --------------------------------------------------------------------------- #
# The single network touchpoint (monkeypatched in tests)
# --------------------------------------------------------------------------- #
def _http_get(url: str, timeout: float = 6.0) -> bytes:
    req = Request(url, headers={"User-Agent": f"GoodCup/0.1 (mailto:{CONTACT_EMAIL})"})
    try:
        with urlopen(req, timeout=timeout) as resp:  # noqa: S310 (trusted, fixed hosts)
            return resp.read()
    except (URLError, TimeoutError, OSError) as exc:  # offline / DNS / timeout / reset
        raise LiteratureUnavailable(str(exc)) from exc


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", text)).strip() or None


# --------------------------------------------------------------------------- #
# Per-source parsers
# --------------------------------------------------------------------------- #
def _parse_crossref(payload: bytes, limit: int) -> list[Paper]:
    items = json.loads(payload).get("message", {}).get("items", [])
    papers = []
    for it in items[:limit]:
        titles = it.get("title") or []
        if not titles:
            continue
        authors = ", ".join(
            " ".join(p for p in (a.get("given"), a.get("family")) if p)
            for a in it.get("author", [])
        ) or None
        parts = (it.get("issued", {}).get("date-parts") or [[None]])[0]
        year = parts[0] if parts and isinstance(parts[0], int) else None
        venue = (it.get("container-title") or [None])[0]
        doi = it.get("DOI")
        papers.append(Paper(
            title=_clean(titles[0]), doi=doi, authors=authors, year=year,
            venue=_clean(venue), abstract=_clean(it.get("abstract")),
            url=it.get("URL") or (f"https://doi.org/{doi}" if doi else None),
            source_api="crossref",
        ))
    return papers


def _parse_semantic_scholar(payload: bytes, limit: int) -> list[Paper]:
    data = json.loads(payload).get("data", [])
    papers = []
    for it in data[:limit]:
        if not it.get("title"):
            continue
        authors = ", ".join(a.get("name", "") for a in it.get("authors", [])) or None
        doi = (it.get("externalIds") or {}).get("DOI")
        papers.append(Paper(
            title=_clean(it.get("title")), doi=doi, authors=authors,
            year=it.get("year"), venue=_clean(it.get("venue")),
            abstract=_clean(it.get("abstract")),
            url=it.get("url") or (f"https://doi.org/{doi}" if doi else None),
            source_api="semantic_scholar",
        ))
    return papers


def _parse_arxiv(payload: bytes, limit: int) -> list[Paper]:
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(payload)
    papers = []
    for entry in root.findall("a:entry", ns)[:limit]:
        title = _clean(entry.findtext("a:title", default="", namespaces=ns))
        if not title:
            continue
        authors = ", ".join(
            n.text.strip() for n in entry.findall("a:author/a:name", ns) if n.text
        ) or None
        published = entry.findtext("a:published", default="", namespaces=ns)
        year = int(published[:4]) if published[:4].isdigit() else None
        papers.append(Paper(
            title=title, doi=None, authors=authors, year=year, venue="arXiv",
            abstract=_clean(entry.findtext("a:summary", default="", namespaces=ns)),
            url=entry.findtext("a:id", default=None, namespaces=ns),
            source_api="arxiv",
        ))
    return papers


# --------------------------------------------------------------------------- #
# Public search
# --------------------------------------------------------------------------- #
def search_papers(query: str, source: str = "crossref", limit: int = 8) -> list[dict]:
    """Search a scholarly API and return normalised paper dicts.

    Raises :class:`LiteratureUnavailable` if the API cannot be reached.
    """
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    query = (query or "").strip()
    if not query:
        return []

    if source == "crossref":
        url = f"{CROSSREF_URL}?{urlencode({'query': query, 'rows': limit})}"
        papers = _parse_crossref(_http_get(url), limit)
    elif source == "semantic_scholar":
        fields = "title,abstract,year,venue,authors,externalIds,url"
        url = f"{SEMANTIC_SCHOLAR_URL}?{urlencode({'query': query, 'limit': limit, 'fields': fields})}"
        papers = _parse_semantic_scholar(_http_get(url), limit)
    else:  # arxiv
        url = f"{ARXIV_URL}?search_query=all:{quote_plus(query)}&max_results={limit}"
        papers = _parse_arxiv(_http_get(url), limit)

    return [asdict(p) for p in papers]


# --------------------------------------------------------------------------- #
# Cache (pure/offline)
# --------------------------------------------------------------------------- #
def save_papers(conn, papers: list[dict], query: str | None = None) -> list[int]:
    """Cache normalised papers into ``paper_references``; returns their ids.

    Pure and offline: no network. Dedupes on the paper's source_hash.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ids = []
    for p in papers:
        paper = Paper(**{k: p.get(k) for k in Paper.__dataclass_fields__})
        if not paper.title:
            continue
        row = {
            "doi": paper.doi, "title": paper.title, "authors": paper.authors,
            "year": paper.year, "venue": paper.venue, "abstract": paper.abstract,
            "url": paper.url, "source_api": paper.source_api,
            "query": query, "retrieved_at": now, "source_hash": paper.source_hash(),
        }
        ref_id, _ = models.upsert_reference(conn, row)
        ids.append(ref_id)
    return ids
