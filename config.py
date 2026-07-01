"""Central configuration for GoodCup Roast-to-Cup Intelligence.

Every tunable constant in the system lives here so there is exactly one place to
change behaviour and one place to audit it. The statistical / data-volume gates
(PRD sections 6 and 7) are intentionally conservative. **Do not lower a gate
silently** -- loosening a threshold without a documented reason is a defect, not
a feature. If a gate needs to move, change it here, in the open, with a comment.

All values are plain module-level constants (no framework, no env magic) so a
non-developer can read and edit them.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = ROOT_DIR / "data"
SAMPLES_DIR: Path = DATA_DIR / "samples"
TEMPLATES_DIR: Path = ROOT_DIR / "templates"
REFERENCE_DIR: Path = ROOT_DIR / "src" / "goodcup" / "reference"

#: Location of the single SQLite file. Gitignored; recreatable from schema + seed.
DB_PATH: Path = DATA_DIR / "goodcup.db"

#: Bundled 2016 WCR/SCA Coffee Taster's Flavor Wheel lexicon.
FLAVOR_WHEEL_PATH: Path = REFERENCE_DIR / "flavor_wheel.json"

#: Contact email sent (as a polite ``mailto``) to the Crossref API when pulling
#: published literature. Crossref asks callers to identify themselves; this is
#: the only place it is set. Change it to a real address in production.
CONTACT_EMAIL: str = "roasting@goodcup.local"


# --------------------------------------------------------------------------- #
# AI layer (grounded narration over the analysis layer)
# --------------------------------------------------------------------------- #
#: Which AI provider narrates grounded facts. "mock" is a deterministic, fully
#: offline stand-in (the default -- no API key, no network, no dependency). "claude"
#: selects the real Anthropic-backed provider, which requires the `anthropic` SDK
#: and credentials; it degrades gracefully to an "unavailable" message if missing.
#: The AI layer only narrates numbers computed by the analysis layer -- it never
#: computes a statistic or bypasses the Phase 2 gate, regardless of provider.
AI_PROVIDER: str = "mock"

#: Model id used by the "claude" provider only (ignored by "mock"). Configurable
#: so a deployment can swap it without code changes.
AI_MODEL: str = "claude-opus-4-8"


# --------------------------------------------------------------------------- #
# Phase 2 data-volume gate (PRD section 7) -- HARD gate, conservative on purpose
# --------------------------------------------------------------------------- #
#: Minimum roasts with a matched cupping score before the recommender may run at
#: all. Below this, recommend/similarity.py returns an explanatory message.
PHASE2_MIN_MATCHED_ROASTS: int = 50

#: For a specific recommendation query, the minimum number of historically
#: similar greens (with cupped roasts) required in the neighbourhood before a
#: profile is surfaced. Fewer than this -> "not enough similar history".
PHASE2_MIN_NEIGHBORS: int = 6

#: Preferred neighbourhood size to draw a recommendation from when available.
PHASE2_TARGET_NEIGHBORS: int = 8


# --------------------------------------------------------------------------- #
# Statistical guardrails (PRD section 6)
# --------------------------------------------------------------------------- #
#: N below which every statistic must carry a visible small-sample warning.
SMALL_SAMPLE_WARN_N: int = 30

#: N at or below which we use bootstrap CIs instead of parametric ones.
BOOTSTRAP_MAX_N: int = 30

#: Bootstrap resamples for confidence intervals.
BOOTSTRAP_ITERS: int = 10_000

#: Seed so bootstrap CIs and any resampling are reproducible run-to-run.
RANDOM_SEED: int = 20240517

#: Family-wise / false-discovery alpha for multiple-comparison control.
FDR_ALPHA: float = 0.05

#: Minimum N required before a *within-stratum* correlation (per machine, per
#: process) is computed at all. Stratifying thin data produces noise.
MIN_STRATUM_N: int = 8

#: Cupper-calibration drift threshold: a cupper whose mean signed deviation from
#: the panel's (robust, median) consensus exceeds this AND whose 95% CI excludes
#: zero is flagged as drifting. Units are cup-score points.
CALIBRATION_DRIFT_THRESHOLD: float = 0.75


# --------------------------------------------------------------------------- #
# Roast-metric computation (PRD section 11)
# --------------------------------------------------------------------------- #
#: Rate-of-Rise smoothing window, in seconds. RoR is the discrete derivative of
#: bean temperature; raw RoR is extremely noisy, so it is smoothed with a
#: centred rolling mean spanning roughly this many seconds. Documented default;
#: change here if a different roasting philosophy wants a tighter/looser window.
ROR_SMOOTHING_WINDOW_S: int = 30

#: --- Dry-end (yellowing) fallback -----------------------------------------
#: If a roast curve has no logged dry-end event marker, dry-end is *inferred* as
#: the first time BT crosses this threshold, and the row is flagged as inferred.
#: Values are unit-aware (see TEMP_UNIT_* below); pick the one matching the log.
DRY_END_TEMP_FALLBACK_C: float = 150.0
DRY_END_TEMP_FALLBACK_F: float = 302.0  # 150 C expressed in F

#: --- RoR crash / flick detection ------------------------------------------
#: A "crash" is a sharp, sustained drop in RoR (typically at/after first crack);
#: a "flick" is a subsequent upturn. These are reported as flagged features with
#: a severity, never judged. Heuristic (documented in roast_metrics.py):
#:   crash  = RoR falls by >= ROR_CRASH_DROP over a window and stays down;
#:   flick  = RoR rises by >= ROR_FLICK_RISE after a crash.
#: Units are degrees-per-minute in whatever temperature unit the log uses.
ROR_CRASH_DROP: float = 3.0          # deg/min sustained drop to flag a crash
ROR_CRASH_WINDOW_S: int = 30         # window over which the drop is measured
ROR_FLICK_RISE: float = 1.5          # deg/min rebound after a crash to flag a flick


# --------------------------------------------------------------------------- #
# Temperature units
# --------------------------------------------------------------------------- #
TEMP_UNIT_C: str = "C"
TEMP_UNIT_F: str = "F"
DEFAULT_TEMP_UNIT: str = TEMP_UNIT_C  # used only when a source omits its unit


# --------------------------------------------------------------------------- #
# Seed / demo scenarios (mockup only -- not part of the production data path)
# --------------------------------------------------------------------------- #
#: Roughly how many matched roasts each scenario produces. Chosen so `sparse`
#: sits clearly below the Phase 2 gate and `full` clearly above it.
SEED_SCENARIOS: dict[str, dict[str, int]] = {
    "empty": {"greens": 0, "roasts": 0},
    "sparse": {"greens": 6, "roasts": 20},
    "full": {"greens": 15, "roasts": 80},
}
