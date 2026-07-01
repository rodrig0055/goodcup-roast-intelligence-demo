"""The AI provider abstraction and factory.

A provider turns :class:`GroundedFacts` (real numbers from the analysis layer)
into readable prose, and maps free-text tasting terms onto the flavor wheel. It
must not introduce a number absent from the facts it was given -- that invariant
is what keeps an "AI-native" GoodCup honest, and it is tested.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from goodcup.ai.grounding import GroundedFacts

# The AI provider is an OPTIONAL feature. Read its config defensively so that a
# missing/partial `config` (e.g. an out-of-date deploy) degrades to the offline
# mock instead of crashing the whole dashboard at import time.
try:
    from config import AI_PROVIDER
except Exception:  # ImportError, or config missing the symbol
    AI_PROVIDER = "mock"


class AIProvider(ABC):
    #: Human-readable provider name, shown in the "Simulated AI" badge.
    name: str = "provider"
    #: Whether this provider can produce output right now (mock is always True;
    #: the Claude provider is False without the SDK/credentials).
    available: bool = False
    #: True when output is simulated (canned/templated), not from a real model.
    simulated: bool = True

    @abstractmethod
    def answer(self, question: str, facts: GroundedFacts) -> str:
        """Answer a natural-language question, grounded in ``facts``."""

    @abstractmethod
    def narrate(self, facts: GroundedFacts) -> str:
        """Explain a computed result in plain, correlational language."""

    @abstractmethod
    def synthesize_literature(self, hypothesis: str, papers: list[dict], association: GroundedFacts | None) -> str:
        """Summarize what cached papers say about a hypothesis, next to our data."""

    @abstractmethod
    def map_descriptor(self, term: str, lexicon: dict[str, list]) -> tuple[str | None, str | None, str | None]:
        """Best-effort map an unknown tasting term onto (L1, L2, L3), using the
        known ``lexicon`` (term -> [L1, L2, L3]) as the reference vocabulary. A
        guess is allowed; callers flag the result as AI-mapped."""


def get_provider() -> AIProvider:
    """Return the configured provider. Defaults to the offline mock."""
    if AI_PROVIDER == "gemini":
        from goodcup.ai.gemini import GeminiProvider

        return GeminiProvider()
    from goodcup.ai.mock import MockProvider

    return MockProvider()
