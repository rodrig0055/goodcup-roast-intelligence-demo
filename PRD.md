# PRD — GoodCup Roast-to-Cup Intelligence System

**Owner:** GoodCup R&D (goodcup.ph)
**Consumer of this document:** Claude Code
**Version:** 1.0
**One-line purpose:** Build a local-first system that ingests our green data, roast logs, and cupping scores, tells us *which roast variables actually drive cup quality in our own data*, surfaces cupper calibration drift, and — only once enough data exists — recommends a starting roast profile for a new green based on how similar greens have historically cupped on our machine.

---

## 0. Read this first (instructions to Claude Code)

- **Implement in phases. Do not one-shot the whole system.** Build Phase 0, stop, and wait for real data to be loaded and ingestion verified before touching Phase 1. Do not build Phase 2 at all until the data-volume gate in §7 is met.
- **Do not invent file formats.** Before writing any parser, request real sample files (Artisan `.alog`, a Cropster CSV export, a filled cupping sheet). Inspect the actual bytes. My descriptions of these formats below are approximate and version-dependent; the real files are ground truth.
- **The statistical guardrails in §6 are not optional and not decorative.** They are the core value of this tool. A pipeline that reports correlations without sample sizes, confidence intervals, and multiple-comparison awareness is worse than no tool, because it will produce confident garbage that gets acted on. Treat any request to relax these as a red flag.
- **Minimal dependencies. This is maintained by a small team with limited software staff.** SQLite, not a database server. Streamlit or static reports, not a bespoke web app. If a feature needs a heavy dependency, flag the tradeoff before adding it.
- **Write tests for the roast-metric math before anything depends on it.** A wrong Development-Time-Ratio formula silently corrupts every downstream conclusion. See §12.

---

## 1. Strategic context (why this specific thing)

The LLM/analysis layer of coffee R&D is commoditized — competitors can rent the same models. The only durable edge is a **proprietary, well-structured dataset of our own roasts + cuppings + feedback, with tooling on top that competitors cannot replicate because they lack the data.** This system is that asset. Its defensibility comes entirely from our data, so data quality and honest analysis matter more than model sophistication.

The physical/sensory core of R&D (sourcing, roasting, tasting) is untouched by this tool and remains the real moat. This system amplifies a good operation; it does not substitute for palate or sourcing.

---

## 2. Users and usage

- **Primary:** R&D / head roaster. Runs analyses, reviews correlations, checks profiles for new greens.
- **Secondary:** Cuppers entering scores; QC lead checking calibration.
- **Skill assumption:** Comfortable with spreadsheets and running a single terminal command or clicking a local app. **Not** software engineers. If a non-developer cannot run this with one command after setup, the design has failed.

---

## 3. Guiding constraints (these govern every decision)

1. **Local-first, single-user, offline-capable.** No cloud, no auth, no multi-tenant. One machine, one SQLite file that can be backed up and version-controlled (or synced via the team's existing file storage).
2. **Statistical honesty over apparent insight.** See §6. Better to say "N too small to conclude anything" than to draw a pretty-but-false correlation.
3. **Interpretability over accuracy.** Every recommendation and finding must be explainable ("these 6 historically similar greens cupped highest with this profile shape"). No black-box regressors in Phase 2.
4. **Minimal, boring dependencies.** Every dependency is a maintenance liability for a two-person team.
5. **Data entry must be frictionless** or the dataset never grows and the whole system is dead. Provide CSV templates and an optional entry form.

---

## 4. Non-goals / out of scope (do not build these)

- Green-supplier offer-sheet analysis (separate project; do not fold in).
- Real-time roaster hardware integration / live roast guidance.
- Cloud deployment, user accounts, multi-user sync, mobile apps.
- Any predictive model beyond interpretable nearest-neighbor in Phase 2.
- Inventory management, sales, or accounting features.
- LLM-generated tasting-note marketing copy.

---

## 5. Data model

Use SQLite. Suggested schema (Claude Code may refine names/types, but keep the entities and the raw-vs-derived separation):

### `greens`
`green_id` (PK), `lot_name`, `origin_country`, `region`, `farm_or_coop`, `varietal`, `process` (washed/natural/honey/anaerobic/other), `harvest_year`, `altitude_masl`, `density_g_per_l`, `moisture_pct`, `water_activity`, `screen_size`, `supplier`, `arrival_date`, `price_per_kg`, `notes`.

### `roasts`
`roast_id` (PK), `green_id` (FK), `machine_id`, `roast_date`, `batch_size_g`, `ambient_temp_c`, `ambient_humidity_pct`, `charge_temp`, `turning_point_temp`, `turning_point_time_s`, `dry_end_time_s`, `dry_end_temp`, `fc_start_time_s`, `fc_start_temp`, `fc_end_time_s`, `drop_time_s`, `drop_temp`, `total_time_s`, `dtr_pct` (derived), `roaster_name`, `source_software` (artisan/cropster/manual), `raw_profile_path`, `notes`.
> Derived fields (`turning_point_*`, phase times, `total_time_s`, `dtr_pct`) are computed by `analysis/roast_metrics.py`, **not** hand-entered, when a raw curve exists. When only manual summary data exists, allow direct entry but flag the row as `curve_available = false`.

### `roast_curves`
`roast_id` (FK), `time_s`, `bean_temp` (BT), `env_temp` (ET), `ror` (derived, °/min). One row per sample. This is the time series; keep it separate from the summary `roasts` table.

### `cuppings`
`cupping_id` (PK), `roast_id` (FK), `cupper_name`, `cupping_date`, `session_id`, `form_type` (sca_traditional / cva / custom), `fragrance_aroma`, `flavor`, `aftertaste`, `acidity`, `body`, `balance`, `uniformity`, `clean_cup`, `sweetness`, `overall`, `defect_points`, `total_score`, `descriptors_raw` (free text), `notes`.
> Support **both** the traditional SCA 100-point form and the newer SCA Coffee Value Assessment (CVA). Make scoring columns nullable so either form fits; store `form_type` so analysis can segment by form. Do not assume all rows use the same form.

### `descriptors`
`descriptor_id` (PK), `cupping_id` (FK), `raw_term`, `wheel_category_l1`, `wheel_category_l2`, `wheel_category_l3`. Populated by `analysis/descriptors.py`, which maps free-text terms onto the SCA / World Coffee Research 2016 Coffee Taster's Flavor Wheel.

**Design rule:** raw ingested data is immutable; derived values live in clearly-named columns/tables and are recomputable from raw. Never overwrite raw with derived.

---

## 6. Statistical guardrails (the core requirement)

Every analytical output must obey these. Bake them into the analysis modules and surface them in the dashboard.

1. **Always report N.** No correlation, mean, or comparison is displayed without its sample size next to it.
2. **Confidence intervals, not just point estimates.** For correlations and group differences, report 95% CIs. For N < ~30, use bootstrap CIs rather than parametric ones.
3. **Warn on small samples.** Display a visible warning banner on any statistic computed with N < 30. Do not hide it.
4. **Multiple-comparison control.** When scanning many roast variables against cup score (the default temptation), correct for it — apply Benjamini-Hochberg FDR (preferred) or Bonferroni, and clearly state that scanning K variables inflates false positives. Show both raw and adjusted p-values.
5. **Effect size over p-values.** Lead with correlation coefficients / standardized mean differences and visualizations. Do not let a p < 0.05 be presented as "significant" without its effect size and CI.
6. **Never imply causation.** Language in outputs must be correlational ("associated with"), never causal ("causes"/"improves"). A roast variable correlating with score on our data is a hypothesis to test on the roaster, not a proven lever.
7. **Confounder honesty.** If the dataset mixes machines, origins, or processes, single-variable correlations are confounded. Flag this explicitly and, where N allows, stratify (e.g., correlations *within* one machine, one process).
8. **Refuse to over-conclude.** Below the §7 data gate, the recommendation module is disabled and the correlation views carry an explicit "exploratory only — insufficient data for inference" header.

---

## 7. Data-volume gate for Phase 2

Phase 2 (recommendation) is **hard-gated** and must not run — the module returns an explanatory message instead — until:

- Total roasts with matched cupping scores **≥ 50** (conservative floor; nearest-neighbor on fewer is unreliable), **and**
- For any given recommendation query, at least **6–8 historically similar greens** with cupped roasts exist in the neighborhood, else it returns "not enough similar history to recommend" rather than guessing.

These thresholds are tunable constants in a config file, set conservatively on purpose. Do not lower them without a documented reason. Loosening them silently is a defect.

---

## 8. Phase 0 — Ingestion and storage (build first, then stop)

**Goal:** get our three data sources into the SQLite schema reliably, with sample files as fixtures.

- `ingest/artisan.py` — parse Artisan `.alog` roast profiles. *Approximate* structure (verify against real files): a Python-dict-literal / JSON-like file with a time array (e.g. `timex`), bean-temp and env-temp arrays (e.g. `temp2` = BT, `temp1` = ET), and an event-index array (e.g. `timeindex`) marking CHARGE, dry-end, first-crack start/end, drop, cool. Field names have varied across Artisan versions — **inspect the actual file, do not trust these names.** Extract the full curve into `roast_curves` and the event times into `roasts`.
- `ingest/cropster.py` — parse a Cropster CSV export into the same schema. (Cropster also has an API on some plans; treat CSV as the baseline and API as optional/future.)
- `ingest/manual_csv.py` — ingest hand-entered data via the CSV templates in `/templates`, for roasts logged on paper or other software. Allow summary-only rows (no curve) flagged `curve_available = false`.
- `db/schema.sql` + a small migration/init routine. `db/models.py` for typed access (sqlite3 stdlib or SQLAlchemy — prefer the lighter option).
- Idempotent re-ingestion: re-importing the same file must not create duplicates (dedupe on a natural key or content hash).
- **Deliverable check:** load the provided real sample files, confirm rows land correctly, confirm a re-import creates no duplicates. Then stop and wait.

---

## 9. Phase 1 — Analysis (build after Phase 0 verified)

- `analysis/roast_metrics.py` — compute derived roast metrics from `roast_curves` per the exact definitions in §11. Turning point, phase durations, DTR, RoR series, RoR crash/flick flags. **This module gets tests first (§12).**
- `analysis/correlation.py` — correlate roast metrics against cup scores under **all §6 guardrails**. Output: a ranked table of associations with N, effect size, raw + FDR-adjusted p, 95% CI, and confounder flags. Provide within-stratum views (per machine, per process) when N permits.
- `analysis/calibration.py` — cupper calibration: for coffees scored by multiple cuppers in the same session, quantify inter-cupper score variance and descriptor divergence; flag cuppers drifting from the group. This is a standalone QC win independent of the data gate.
- `analysis/descriptors.py` — normalize free-text descriptors to the 2016 flavor wheel; show which descriptors trend with which origins / roast levels.
- `dashboard/app.py` — Streamlit app presenting the above: a correlations page (guardrails visible), a calibration page, a descriptor page, and a data-entry/upload page. Keep it legible for a non-technical roaster. If Streamlit is judged too heavy, a static HTML report generator is an acceptable substitute — flag the tradeoff.

---

## 10. Phase 2 — Roast-profile recommendation (gated; build only when §7 is met)

- `recommend/similarity.py` — given a new green's characteristics (origin, process, density, moisture, screen size, water activity, altitude), find the k nearest historical greens using standardized numeric features + encoded categoricals, retrieve their cupped roasts, and surface the roast-profile parameters (charge temp, RoR curve shape, phase split, DTR, drop temp) of the **highest-cupping** neighbors.
- **Interpretable by construction:** k-nearest-neighbors, not a black-box regressor. Every recommendation must show *which* historical greens/roasts it's based on, their cup scores, and why they were judged similar. If the neighborhood is too sparse (§7), return "insufficient similar history," never a fabricated profile.
- Output framed as a **starting point for a test roast**, explicitly not a guaranteed answer. The roaster validates it by cupping.

---

## 11. Roast-metric definitions (compute exactly as specified)

All times in seconds from CHARGE unless noted. BT = bean temperature.

- **Total roast time** = `t_drop − t_charge`.
- **Turning point (TP)** = the minimum of the BT curve after charge; record both `turning_point_temp` (the min BT) and `turning_point_time_s`.
- **Drying phase** = `t_charge → t_dry_end`, where dry-end (yellowing) is taken from the logged event marker if present; if absent, allow a temperature-threshold fallback but flag it as inferred.
- **Maillard phase** = `t_dry_end → t_fc_start`.
- **Development phase** = `t_fc_start → t_drop`.
- **Development Time Ratio (DTR)** = `(t_drop − t_fc_start) / (t_drop − t_charge) × 100%`. (Commonly discussed around 15–25%, but this is a philosophy-dependent convention, **not** a target the tool should assume or enforce. Report it; do not judge it.)
- **Rate of Rise (RoR)** = discrete derivative of BT over time, in degrees per minute, smoothed with a rolling window (make window size configurable; document the default). Store per-sample in `roast_curves.ror`.
- **RoR crash** = a sharp sustained drop in RoR (typically around/after first crack); **RoR flick** = a subsequent upturn. Compute as flagged features with a severity measure; document the detection heuristic and make thresholds configurable.

Units: preserve whatever the source uses (°C vs °F) and store the unit; do not silently mix scales. RoR must be consistent with the temperature unit.

---

## 12. Testing requirements (non-negotiable)

- `tests/test_roast_metrics.py` — feed synthetic BT/time curves with known TP, phase boundaries, and DTR; assert the computed values match. This is the highest-priority test file; write it before anything consumes the metrics.
- `tests/test_ingest_*.py` — round-trip tests per parser using the real sample files as fixtures; assert row counts, event times, and dedupe-on-reimport.
- `tests/test_schema.py` — schema integrity, FK constraints, immutability of raw tables.
- CI is out of scope; tests must run locally with one command (`pytest`).

---

## 13. Tech stack and repo structure

**Stack:** Python 3.11+, `pandas`, `numpy`, `scipy` (stats/bootstrap), `scikit-learn` (only for standardization + nearest-neighbors in Phase 2), a plotting lib (`plotly` or `matplotlib`), `streamlit` (dashboard), SQLite via stdlib `sqlite3` or lightweight SQLAlchemy. Keep the dependency list short and justified.

**Repo:**
```
goodcup-rnd/
  CLAUDE.md              # instructions for Claude Code working in this repo
  README.md              # setup + one-command run for non-developers
  PRD.md                 # this document
  requirements.txt       # (or pyproject.toml)
  config.py              # tunable constants: N gates, RoR window, thresholds
  data/
    samples/             # real sample files provided by GoodCup (fixtures)
    goodcup.db           # gitignored
  templates/
    green_intake.csv
    cupping_entry.csv
    roast_manual.csv
  src/goodcup/
    ingest/  {artisan.py, cropster.py, manual_csv.py}
    db/      {schema.sql, models.py}
    analysis/{roast_metrics.py, correlation.py, calibration.py, descriptors.py}
    recommend/{similarity.py}
    dashboard/{app.py}
  tests/     {test_roast_metrics.py, test_ingest_*.py, test_schema.py}
```

Generate a `CLAUDE.md` capturing the guardrails (§0, §6, §7) and the phase discipline, so future Claude Code sessions in this repo inherit the constraints.

---

## 14. Success criteria

The build succeeds if:

1. It answers, honestly, *"which roast variables are associated with cup score in our own data, how strongly, with what N and confidence, and with confounders flagged"* — and refuses to over-claim on thin data.
2. It surfaces cupper calibration drift the team didn't already have visibility into.
3. A non-developer on the team can run it and enter data with minimal friction.
4. (Phase 2, once gated open) For a new green, it proposes a starting profile that the head roaster judges plausible **and** that beats the naive default profile in a blind cupping at least some of the time. That blind-cupping test — not the code compiling — is the real bar.

If it produces analyses but no one's roasting or buying decision ever changes because of it, it failed regardless of code quality.

---

## 15. How to drive Claude Code with this document

1. Create an empty repo, drop in `PRD.md` and a stub `CLAUDE.md`.
2. Provide 2–3 **real** `.alog` files (or Cropster CSVs) and 1–2 filled cupping sheets before asking for any parser.
3. Instruct: *"Read PRD.md. Implement Phase 0 only. Use the sample files in data/samples/ as fixtures. Do not proceed to Phase 1."*
4. Load your real data, verify ingestion, then authorize Phase 1.
5. Personally check `roast_metrics.py` against one roast you've hand-computed. If TP/DTR/phases are wrong, everything downstream is wrong.
6. Require `pytest` green before advancing between phases.
7. Do **not** authorize Phase 2 until the §7 data gate is genuinely met.

---

## 16. Open questions — answer these before/while building

1. What roast software produces your logs today — Artisan, Cropster, something else, or paper? (Determines which parser is real vs. stub.)
2. Which cupping form: traditional SCA 100-point, the SCA CVA, or a custom in-house form?
3. **How many historical roasts with matched cupping scores do you have *right now*?** This single number decides whether Phase 2 is buildable or whether you're stuck at Phase 1 until you accumulate more.
4. One roasting machine or several? (Multiple machines are a confounder small data cannot cleanly separate.)
5. One roaster's palate, or multiple cuppers? (Determines whether calibration analysis has anything to work with.)
6. Who enters data, and how often? (If the answer is "no one reliably," fix that before building, or the dataset never grows.)

---

> ## Prototype note (this build)
>
> This repository is a **client-facing prototype/mockup**. Two deviations from the
> letter of the PRD were explicitly authorised for the demo, and *only* these:
>
> 1. **Sample files are synthetic.** No real Artisan/Cropster/cupping files were
>    available, so realistic synthetic fixtures were generated (clearly labelled).
>    All three parsers are built and tested against them. If real client files
>    arrive, verify the parsers against the actual bytes (per §0/§8).
> 2. **All phases are built end-to-end** rather than stopping after Phase 0, so the
>    client can see the full vision. The phase *architecture*, the statistical
>    guardrails (§6), and the config-driven data gate (§7) are preserved exactly --
>    those are the product. The `seed` scenarios (`empty`/`sparse`/`full`) let the
>    demo show the tool behaving correctly at every data volume, including the gate
>    refusing to recommend below 50 matched roasts.
>
> Everything else follows the PRD.
