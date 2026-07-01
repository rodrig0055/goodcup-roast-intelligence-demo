"""Real Google Gemini provider.

Narrates the SAME grounded facts the mock does, so the honesty contract is
unchanged: the model is handed the numbers computed by the analysis layer and
instructed to use only those, in correlational language, and the UI still renders
the evidence table beside every answer. Gemini adds fluency, not new numbers.

Key handling: read from the ``GEMINI_API_KEY`` environment variable, or a
Streamlit secret of the same name. The key is NEVER hardcoded or written to disk.
Network/credential problems degrade to a clear message (the app never crashes) —
the same philosophy as ``research/literature.py``.

Uses the REST endpoint via stdlib ``urllib`` (no new dependency), with verified
TLS through certifi when available.
"""

from __future__ import annotations

import json
import os
import ssl
from urllib.error import URLError
from urllib.request import Request, urlopen

from config import GEMINI_MODEL
from goodcup.ai.grounding import GroundedFacts, fmt
from goodcup.ai.provider import AIProvider

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_SYSTEM_RULES = (
    "You are the GoodCup roasting analyst. You are given FACTS already computed by a "
    "statistics engine. Rules you must follow exactly:\n"
    "1. Use ONLY the numbers present in the FACTS. Never invent, round differently, or "
    "estimate a number that is not given.\n"
    "2. Use correlational language only ('associated with', 'tracks'), never causal "
    "('causes', 'proves', 'because of').\n"
    "3. Be concise and practical for a head roaster. 2-4 sentences.\n"
    "4. If the FACTS say the request is unavailable or gated, explain that plainly and "
    "do not fabricate an answer."
)


class GeminiProvider(AIProvider):
    name = f"Gemini ({GEMINI_MODEL})"
    simulated = False

    def __init__(self) -> None:
        self._key = _load_key()
        self.available = bool(self._key)

    # ----------------------------------------------------------------- #
    def answer(self, question: str, facts: GroundedFacts) -> str:
        prompt = f"QUESTION: {question}\n\nFACTS ({facts.analysis}):\n{_facts_text(facts)}"
        return self._generate(prompt)

    def narrate(self, facts: GroundedFacts) -> str:
        prompt = f"Explain this result in plain language.\n\nFACTS ({facts.analysis}):\n{_facts_text(facts)}"
        return self._generate(prompt)

    def synthesize_literature(self, hypothesis, papers, association) -> str:
        if not papers:
            return "No papers are cached for this hypothesis yet — search the literature panel first."
        cited = "\n".join(f"- {p.get('title', 'untitled')} ({p.get('year', 'n.d.')})" for p in papers[:6])
        assoc = _facts_text(association) if association and association.available else "none"
        prompt = (
            f"Summarize what these cached papers suggest about the hypothesis \"{hypothesis}\", "
            f"as external evidence (not proof for this roastery). Then relate it to our own data.\n\n"
            f"PAPERS:\n{cited}\n\nOUR DATA FACTS:\n{assoc}"
        )
        return self._generate(prompt)

    def map_descriptor(self, term: str, lexicon: dict[str, list]):
        if not self.available:
            return (None, None, None)
        vocab = sorted({tuple(v) for v in lexicon.values() if v and v[0]})
        options = "; ".join(f"{t[0]}>{t[1] or ''}>{t[2] or ''}" for t in vocab)
        prompt = (
            f"Map the coffee tasting term \"{term}\" onto the 2016 WCR/SCA flavor wheel. "
            f"Choose the single closest category path from this list, or answer NONE if nothing fits.\n"
            f"OPTIONS (L1>L2>L3): {options}\n"
            f"Reply with ONLY the chosen path exactly as written (e.g. Fruity>Citrus Fruit>Lemon), or NONE."
        )
        reply = self._generate(prompt, _system=False).strip()
        if not reply or reply.upper().startswith("NONE"):
            return (None, None, None)
        parts = [p.strip() or None for p in reply.split(">")]
        parts = (parts + [None, None, None])[:3]
        # only accept a mapping that matches a real wheel path (no invented categories)
        if tuple(parts) in vocab:
            return (parts[0], parts[1], parts[2])
        return (None, None, None)

    # ----------------------------------------------------------------- #
    def _generate(self, prompt: str, _system: bool = True) -> str:
        if not self.available:
            return (
                "Gemini is selected but no API key is available (set GEMINI_API_KEY, or a "
                "Streamlit secret of that name). Switch AI_PROVIDER to \"mock\" for the offline demo. "
                "No numbers are fabricated in the meantime."
            )
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if _system:
            body["systemInstruction"] = {"parts": [{"text": _SYSTEM_RULES}]}
        try:
            raw = _post(_ENDPOINT.format(model=GEMINI_MODEL), self._key, body)
            data = json.loads(raw)
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip() or "(Gemini returned an empty response.)"
        except (URLError, TimeoutError, OSError) as exc:
            return f"Gemini is unreachable right now ({exc}). Try again, or use the offline mock."
        except (KeyError, IndexError, ValueError):
            return "Gemini returned an unexpected response. Try again, or use the offline mock."


# --------------------------------------------------------------------------- #
def _load_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    try:  # optional: Streamlit secrets, without importing streamlit at module load
        import streamlit as st

        return st.secrets.get("GEMINI_API_KEY")  # type: ignore[no-any-return]
    except Exception:
        return None


def _ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return None


def _post(url: str, key: str, body: dict, timeout: float = 20.0) -> bytes:
    req = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-goog-api-key": key},
        method="POST",
    )
    with urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # noqa: S310 (fixed host)
        return resp.read()


def _facts_text(facts: GroundedFacts) -> str:
    if not facts.available:
        return f"UNAVAILABLE: {facts.refusal}"
    lines = []
    for row in facts.summary_rows:
        lines.append(", ".join(f"{k}={fmt(v) if isinstance(v, (int, float)) else v}" for k, v in row.items()))
    if facts.notes:
        lines.append("NOTE: " + " ".join(facts.notes))
    return "\n".join(lines)
