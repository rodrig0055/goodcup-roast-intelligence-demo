"""Real Anthropic-backed provider — INERT SCAFFOLD, not wired for use yet.

This exists to document the drop-in path and to make the future swap a small,
well-defined change. It is only constructed when ``config.AI_PROVIDER == "claude"``.
The `anthropic` SDK is imported lazily *inside* methods, so this module imports
fine without the dependency, and selecting it without the SDK/credentials degrades
to a clear "unavailable" message rather than crashing (mirroring the literature
module's ``LiteratureUnavailable`` degradation).

No `anthropic` dependency is added and no network call is made in the current
build. To activate later: `pip install anthropic`, set `AI_PROVIDER="claude"`,
provide credentials (env `ANTHROPIC_API_KEY` or an `ant auth login` profile), and
fill in the method bodies below following the commented call shape.

The honesty contract is unchanged from the mock: the model receives the same
:class:`GroundedFacts` and must narrate only the numbers already in them. The
assistant would use tool-use to call the grounding fact-gatherers; the other
methods pass facts as context and constrain output to them.
"""

from __future__ import annotations

from goodcup.ai.grounding import GroundedFacts
from goodcup.ai.provider import AIProvider

try:
    from config import AI_MODEL
except Exception:
    AI_MODEL = "claude-opus-4-8"


def _load_client():
    """Return an Anthropic client, or None if the SDK/credentials are absent."""
    try:
        import anthropic  # noqa: F401  (optional dependency; not installed by default)
    except Exception:
        return None
    try:
        return anthropic.Anthropic()  # resolves env key / ant-auth profile
    except Exception:
        return None


_UNAVAILABLE = (
    "The Claude provider is selected but unavailable (the `anthropic` SDK or "
    "credentials are missing). Set AI_PROVIDER=\"mock\" for the offline demo, or "
    "install the SDK and provide a key. No numbers are fabricated in the meantime."
)


class ClaudeProvider(AIProvider):
    name = f"Claude ({AI_MODEL})"
    simulated = False

    def __init__(self) -> None:
        self._client = _load_client()
        self.available = self._client is not None

    # Each method: if unavailable, degrade clearly. Otherwise call the API with
    # the facts as grounded context. Bodies are intentionally left as the
    # documented drop-in point; the mock provider serves the current build.
    def answer(self, question: str, facts: GroundedFacts) -> str:
        if not self.available:
            return _UNAVAILABLE
        # DROP-IN: client.messages.create(model=AI_MODEL, thinking={"type": "adaptive"},
        #   system=<grounding contract: narrate only these numbers>, messages=[...facts, question])
        raise NotImplementedError("ClaudeProvider.answer is the documented drop-in point.")

    def narrate(self, facts: GroundedFacts) -> str:
        if not self.available:
            return _UNAVAILABLE
        raise NotImplementedError("ClaudeProvider.narrate is the documented drop-in point.")

    def synthesize_literature(self, hypothesis, papers, association) -> str:
        if not self.available:
            return _UNAVAILABLE
        raise NotImplementedError("ClaudeProvider.synthesize_literature is the documented drop-in point.")

    def map_descriptor(self, term: str, lexicon: dict[str, list]):
        if not self.available:
            return (None, None, None)
        raise NotImplementedError("ClaudeProvider.map_descriptor is the documented drop-in point.")
