-- GoodCup Roast-to-Cup Intelligence -- SQLite schema.
--
-- Design rule (PRD section 5): raw ingested data is IMMUTABLE; derived values
-- live in clearly-named columns/tables and are recomputable from raw. Raw is
-- never overwritten with derived. This is enforced two ways:
--   * derived columns are grouped and commented "-- DERIVED" below;
--   * BEFORE UPDATE triggers block edits to raw curve samples and raw cupping
--     observations (see bottom of file).
--
-- Foreign keys are declared here but SQLite only enforces them when
-- `PRAGMA foreign_keys = ON` is set per-connection (done in models.get_connection).

-- --------------------------------------------------------------------------- --
-- greens: one row per green-coffee lot.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS greens (
    green_id        INTEGER PRIMARY KEY,
    lot_name        TEXT NOT NULL,
    origin_country  TEXT,
    region          TEXT,
    farm_or_coop    TEXT,
    varietal        TEXT,
    process         TEXT,                 -- washed/natural/honey/anaerobic/other
    harvest_year    INTEGER,
    altitude_masl   REAL,
    density_g_per_l REAL,
    moisture_pct    REAL,
    water_activity  REAL,
    screen_size     REAL,
    supplier        TEXT,
    arrival_date    TEXT,                 -- ISO-8601 date
    price_per_kg    REAL,
    notes           TEXT,
    -- dedupe key for idempotent re-ingestion (content hash of the source row)
    source_hash     TEXT UNIQUE
);

-- --------------------------------------------------------------------------- --
-- roasts: one row per roast batch. Holds raw event readings from the log AND
-- derived summary metrics. Derived columns are recomputed by
-- analysis/roast_metrics.py from roast_curves; do not hand-edit them when a
-- curve exists.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS roasts (
    roast_id            INTEGER PRIMARY KEY,
    green_id            INTEGER NOT NULL REFERENCES greens(green_id),
    machine_id          TEXT,
    roaster_name        TEXT,
    roast_ref           TEXT,             -- human batch code, e.g. "R-2026-014"; links cupping sheets
    roast_date          TEXT,             -- ISO-8601
    batch_size_g        REAL,
    ambient_temp_c      REAL,
    ambient_humidity_pct REAL,
    temp_unit           TEXT NOT NULL DEFAULT 'C',   -- 'C' or 'F'; never mix

    -- raw event readings (from the log / manual entry) ----------------------
    charge_temp         REAL,
    dry_end_time_s      REAL,
    dry_end_temp        REAL,
    fc_start_time_s     REAL,
    fc_start_temp       REAL,
    fc_end_time_s       REAL,
    fc_end_temp         REAL,
    drop_time_s         REAL,
    drop_temp           REAL,

    -- DERIVED (computed from roast_curves by roast_metrics.py) ---------------
    turning_point_temp  REAL,             -- DERIVED: min BT after charge
    turning_point_time_s REAL,            -- DERIVED
    total_time_s        REAL,             -- DERIVED: t_drop - t_charge
    drying_time_s       REAL,             -- DERIVED: charge -> dry_end
    maillard_time_s     REAL,             -- DERIVED: dry_end -> fc_start
    development_time_s  REAL,             -- DERIVED: fc_start -> drop
    dtr_pct             REAL,             -- DERIVED: development / total * 100
    dry_end_inferred    INTEGER DEFAULT 0,-- DERIVED: 1 if dry-end came from temp fallback
    ror_crash           INTEGER DEFAULT 0,-- DERIVED: 1 if a RoR crash was detected
    ror_crash_severity  REAL,             -- DERIVED: magnitude of the crash (deg/min)
    ror_flick           INTEGER DEFAULT 0,-- DERIVED: 1 if a RoR flick was detected
    ror_flick_severity  REAL,             -- DERIVED: magnitude of the flick (deg/min)

    -- provenance ------------------------------------------------------------
    source_software     TEXT,             -- artisan / cropster / manual
    raw_profile_path    TEXT,
    curve_available     INTEGER NOT NULL DEFAULT 0,  -- 0 = summary-only row
    notes               TEXT,
    source_hash         TEXT UNIQUE       -- dedupe key
);

-- --------------------------------------------------------------------------- --
-- roast_curves: the time series. One row per sample. RAW = (time_s, bean_temp,
-- env_temp); DERIVED = ror. Kept separate from the summary `roasts` table.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS roast_curves (
    curve_id    INTEGER PRIMARY KEY,
    roast_id    INTEGER NOT NULL REFERENCES roasts(roast_id) ON DELETE CASCADE,
    time_s      REAL NOT NULL,            -- RAW: seconds from CHARGE
    bean_temp   REAL,                     -- RAW: BT
    env_temp    REAL,                     -- RAW: ET
    ror         REAL,                     -- DERIVED: smoothed deg/min
    UNIQUE (roast_id, time_s)
);

-- --------------------------------------------------------------------------- --
-- cuppings: one row per (coffee, cupper, session) score sheet. Score columns
-- are nullable so both SCA-traditional and CVA forms fit; `form_type` records
-- which. These are RAW observations -> immutable once entered.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS cuppings (
    cupping_id      INTEGER PRIMARY KEY,
    roast_id        INTEGER NOT NULL REFERENCES roasts(roast_id) ON DELETE CASCADE,
    cupper_name     TEXT,
    cupping_date    TEXT,                 -- ISO-8601
    session_id      TEXT,                 -- groups cuppers who tasted together
    form_type       TEXT,                 -- sca_traditional / cva / custom

    -- score components (nullable; presence depends on form_type) -------------
    fragrance_aroma REAL,
    flavor          REAL,
    aftertaste      REAL,
    acidity         REAL,
    body            REAL,
    balance         REAL,
    uniformity      REAL,
    clean_cup       REAL,
    sweetness       REAL,
    overall         REAL,
    defect_points   REAL,
    total_score     REAL,

    descriptors_raw TEXT,                 -- free-text tasting notes (RAW)
    notes           TEXT,
    source_hash     TEXT UNIQUE           -- dedupe key
);

-- --------------------------------------------------------------------------- --
-- descriptors: DERIVED. Free-text terms from cuppings.descriptors_raw mapped
-- onto the 2016 WCR/SCA flavor wheel by analysis/descriptors.py. Fully
-- recomputable; safe to delete + rebuild.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS descriptors (
    descriptor_id     INTEGER PRIMARY KEY,
    cupping_id        INTEGER NOT NULL REFERENCES cuppings(cupping_id) ON DELETE CASCADE,
    raw_term          TEXT,
    wheel_category_l1 TEXT,
    wheel_category_l2 TEXT,
    wheel_category_l3 TEXT
);

-- --------------------------------------------------------------------------- --
-- Indices
-- --------------------------------------------------------------------------- --
CREATE INDEX IF NOT EXISTS idx_roasts_green    ON roasts(green_id);
CREATE INDEX IF NOT EXISTS idx_curves_roast    ON roast_curves(roast_id);
CREATE INDEX IF NOT EXISTS idx_cuppings_roast  ON cuppings(roast_id);
CREATE INDEX IF NOT EXISTS idx_cuppings_session ON cuppings(session_id);
CREATE INDEX IF NOT EXISTS idx_descriptors_cup ON descriptors(cupping_id);

-- --------------------------------------------------------------------------- --
-- Views
-- --------------------------------------------------------------------------- --
-- One row per cupping, joined to its roast and green. Used for per-cupping
-- analysis (correlation, calibration) where cupper identity matters.
DROP VIEW IF EXISTS roast_cupping;
CREATE VIEW roast_cupping AS
SELECT
    c.cupping_id, c.roast_id, c.cupper_name, c.cupping_date, c.session_id,
    c.form_type, c.total_score, c.flavor, c.acidity, c.body, c.aftertaste,
    c.balance, c.sweetness, c.overall, c.descriptors_raw,
    r.green_id, r.machine_id, r.roaster_name, r.temp_unit,
    r.charge_temp, r.drop_temp, r.total_time_s, r.dtr_pct,
    r.development_time_s, r.drying_time_s, r.maillard_time_s,
    r.turning_point_temp, r.turning_point_time_s,
    r.ror_crash, r.ror_flick, r.curve_available,
    g.origin_country, g.region, g.process, g.varietal,
    g.density_g_per_l, g.moisture_pct, g.water_activity,
    g.altitude_masl, g.screen_size
FROM cuppings c
JOIN roasts r ON r.roast_id = c.roast_id
JOIN greens g ON g.green_id = r.green_id;

-- One row per roast that has >= 1 cupping, with the mean cup score across
-- cuppers. This is the "matched roasts" set the Phase 2 gate counts (PRD 7)
-- and the roast-level correlation set.
DROP VIEW IF EXISTS matched_roasts;
CREATE VIEW matched_roasts AS
SELECT
    r.roast_id, r.green_id, r.machine_id, r.roaster_name, r.temp_unit,
    r.charge_temp, r.drop_temp, r.total_time_s, r.dtr_pct,
    r.development_time_s, r.drying_time_s, r.maillard_time_s,
    r.turning_point_temp, r.turning_point_time_s,
    r.ror_crash, r.ror_flick, r.curve_available,
    g.origin_country, g.process, g.varietal,
    g.density_g_per_l, g.moisture_pct, g.water_activity,
    g.altitude_masl, g.screen_size,
    AVG(c.total_score) AS mean_total_score,
    COUNT(c.cupping_id) AS n_cuppings
FROM roasts r
JOIN greens g ON g.green_id = r.green_id
JOIN cuppings c ON c.roast_id = r.roast_id
WHERE c.total_score IS NOT NULL
GROUP BY r.roast_id;

-- --------------------------------------------------------------------------- --
-- Immutability triggers: raw ingested data may not be UPDATEd. Derived columns
-- (roast_curves.ror, and all roasts.* DERIVED columns) are intentionally NOT
-- listed, so recomputation is allowed.
-- --------------------------------------------------------------------------- --
DROP TRIGGER IF EXISTS trg_roast_curves_raw_immutable;
CREATE TRIGGER trg_roast_curves_raw_immutable
BEFORE UPDATE OF time_s, bean_temp, env_temp ON roast_curves
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT,
        'roast_curves raw columns (time_s, bean_temp, env_temp) are immutable; recompute derived ror instead');
END;

DROP TRIGGER IF EXISTS trg_cuppings_raw_immutable;
CREATE TRIGGER trg_cuppings_raw_immutable
BEFORE UPDATE OF fragrance_aroma, flavor, aftertaste, acidity, body, balance,
                 uniformity, clean_cup, sweetness, overall, defect_points,
                 total_score, descriptors_raw, cupper_name, form_type
ON cuppings
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT,
        'cuppings raw observation columns are immutable; correct by re-ingesting the source');
END;

-- --------------------------------------------------------------------------- --
-- experiments: durable R&D decision records (Experiment Lab). App-authored
-- institutional memory, NOT ingested raw data -- freely updatable, no trigger.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id  INTEGER PRIMARY KEY,
    created_at     TEXT,                  -- ISO-8601
    title          TEXT NOT NULL,
    green_id       INTEGER REFERENCES greens(green_id) ON DELETE SET NULL,
    hypothesis     TEXT,
    variable       TEXT,                  -- what was deliberately changed
    success_rule   TEXT,
    status         TEXT,                  -- draft / ready / decided
    blind_results  TEXT,                  -- JSON: ranking, means, spreads
    decision       TEXT,
    owner          TEXT,
    source_hash    TEXT UNIQUE            -- dedupe key
);
CREATE INDEX IF NOT EXISTS idx_experiments_green ON experiments(green_id);

-- --------------------------------------------------------------------------- --
-- paper_references: scholarly papers pulled on demand from free APIs
-- (Crossref / Semantic Scholar / arXiv) and cached so they are available
-- offline and citable in decision records. App-authored cache; updatable.
-- --------------------------------------------------------------------------- --
CREATE TABLE IF NOT EXISTS paper_references (
    reference_id   INTEGER PRIMARY KEY,
    doi            TEXT,
    title          TEXT NOT NULL,
    authors        TEXT,
    year           INTEGER,
    venue          TEXT,
    abstract       TEXT,
    url            TEXT,
    source_api     TEXT,                  -- crossref / semantic_scholar / arxiv
    query          TEXT,                  -- the search that surfaced it
    retrieved_at   TEXT,                  -- ISO-8601
    source_hash    TEXT UNIQUE            -- dedupe key (doi or normalised title)
);

-- Join: which cached papers support which experiments/hypotheses.
CREATE TABLE IF NOT EXISTS experiment_references (
    experiment_id  INTEGER NOT NULL REFERENCES experiments(experiment_id) ON DELETE CASCADE,
    reference_id   INTEGER NOT NULL REFERENCES paper_references(reference_id) ON DELETE CASCADE,
    PRIMARY KEY (experiment_id, reference_id)
);
