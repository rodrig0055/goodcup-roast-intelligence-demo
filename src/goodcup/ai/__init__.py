"""AI-native layer: grounded narration over the deterministic analysis layer.

The governing rule (see PRODUCT.md anti-references and CLAUDE.md guardrails):
the LLM narrates and maps -- it never computes a statistic, invents a number, or
bypasses a gate. Every figure a provider presents is computed here, in the
grounding layer, and handed to the provider as plain data.
"""
