"""Generate a customer-facing Roastery Brew Sheet from the roast/cupping record.

This is the outward end of the same knowledge chain the app captures internally:
green -> roast -> cupping -> descriptors -> brew guide. It is deliberately honest
about provenance:

* **Measured** fields come straight from the data -- lot facts (`greens`), the
  "in the cup" flavour notes (the descriptor mapping over this lot's cuppings),
  and the expected sensory profile (the lot's cupping component means, with N).
* The **recipe** is a *starting point*, templated by method and the inferred
  roast level. It is never presented as measured; the renderer labels it as an
  editable "dial by taste" suggestion.

If a lot has no cuppings yet, the sensory/flavour sections say so rather than
inventing notes.
"""

from __future__ import annotations

from datetime import date

from goodcup.db import models

# Brewing recipe templates. These are conventional starting points, NOT data
# measured by GoodCup -- the renderer marks them as such.
METHODS = {
    "Hario V60-02": {
        "dose_g": 12, "ratio": 16, "grind": "Medium-fine",
        "grinders": {"Comandante C40": "26 clicks", "1Zpresso JX": "8·3 rev", "Baratza Encore": "18"},
        "pours": [
            ("0:00", "Bloom", "2x dose, gentle spiral, no stir"),
            ("0:35", "Pour 2", "spiral out then taper at the rim, steady rate"),
            ("1:10", "Pour 3", "centre pour, keep the bed flat"),
            ("Drawdown", "Finish", "let the bed clear; dial by taste if thin or dry"),
        ],
    },
    "Kalita Wave 155": {
        "dose_g": 20, "ratio": 15, "grind": "Medium",
        "grinders": {"Comandante C40": "30 clicks", "1Zpresso JX": "9·0 rev", "Baratza Encore": "22"},
        "pours": [
            ("0:00", "Bloom", "2.5x dose, wet all grounds"),
            ("0:40", "Pour 2", "concentric pours to keep the bed even"),
            ("1:20", "Pour 3", "top up in short pulses"),
            ("Drawdown", "Finish", "aim to finish level; adjust grind by taste"),
        ],
    },
}
DEFAULT_METHOD = "Hario V60-02"

# Water temperature (°C) suggested by roast level -- a starting point only.
_TEMP_BY_LEVEL = {"Light": 94, "Light-medium": 93, "Medium": 91, "Medium-dark": 89, "Dark": 87}


def infer_roast_level(drop_temp_c: float | None) -> tuple[str, str]:
    """Infer a roast-level label from median drop temperature (°C).

    Returns (label, basis). Honest heuristic; the basis string is shown so the
    reader knows it was derived, not recorded.
    """
    if drop_temp_c is None:
        return ("Unspecified", "no drop temperature recorded")
    basis = f"inferred from {drop_temp_c:.0f}°C drop temperature"
    if drop_temp_c < 205:
        return ("Light", basis)
    if drop_temp_c < 210:
        return ("Light-medium", basis)
    if drop_temp_c < 215:
        return ("Medium", basis)
    if drop_temp_c < 220:
        return ("Medium-dark", basis)
    return ("Dark", basis)


def _top_flavor_notes(conn, green_id: int, limit: int = 4) -> list[str]:
    """The lot's most-mentioned mapped flavour terms (measured from cuppings)."""
    rows = models.read_sql(
        conn,
        """
        SELECT COALESCE(d.wheel_category_l3, d.wheel_category_l2, d.raw_term) AS note,
               COUNT(*) AS n
        FROM descriptors d
        JOIN cuppings c ON c.cupping_id = d.cupping_id
        JOIN roasts r   ON r.roast_id = c.roast_id
        WHERE r.green_id = ? AND d.wheel_category_l1 IS NOT NULL
        GROUP BY note ORDER BY n DESC, note ASC LIMIT ?
        """,
        [green_id, limit],
    )
    return [str(x).lower() for x in rows["note"].tolist()]


def build_brew_sheet(conn, green_id: int, method: str = DEFAULT_METHOD) -> dict:
    """Assemble the brew-sheet data for one green lot."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {sorted(METHODS)}")
    green_row = conn.execute("SELECT * FROM greens WHERE green_id = ?", (green_id,)).fetchone()
    if green_row is None:
        raise ValueError(f"no green lot with id {green_id}")
    green = dict(green_row)

    agg = conn.execute(
        """
        SELECT AVG(r.drop_temp) AS drop_temp,
               AVG(c.acidity) AS acidity, AVG(c.body) AS body,
               AVG(c.sweetness) AS sweetness, AVG(c.total_score) AS score,
               COUNT(c.cupping_id) AS n_cuppings
        FROM roasts r LEFT JOIN cuppings c ON c.roast_id = r.roast_id
        WHERE r.green_id = ?
        """,
        (green_id,),
    ).fetchone()
    n_cuppings = int(agg["n_cuppings"] or 0)
    level, level_basis = infer_roast_level(agg["drop_temp"])

    tpl = METHODS[method]
    water_g = tpl["dose_g"] * tpl["ratio"]
    recipe = {
        "method": method,
        "dose_g": tpl["dose_g"],
        "water_g": water_g,
        "ratio": f"1:{tpl['ratio']}",
        "temp_c": _TEMP_BY_LEVEL.get(level, 92),
        "grind": tpl["grind"],
        "grinders": tpl["grinders"],
        "pours": tpl["pours"],
    }

    sensory = None
    if n_cuppings > 0 and agg["acidity"] is not None:
        sensory = {
            "acidity": round(agg["acidity"], 1),
            "sweetness": round(agg["sweetness"], 1) if agg["sweetness"] is not None else None,
            "body": round(agg["body"], 1) if agg["body"] is not None else None,
            "score": round(agg["score"], 1) if agg["score"] is not None else None,
            "n": n_cuppings,
        }

    return {
        "lot_name": green.get("lot_name"),
        "region": green.get("region"),
        "origin_country": green.get("origin_country"),
        "process": green.get("process"),
        "varietal": green.get("varietal"),
        "altitude_masl": green.get("altitude_masl"),
        "roast_level": level,
        "roast_level_basis": level_basis,
        "flavor_notes": _top_flavor_notes(conn, green_id),
        "n_cuppings": n_cuppings,
        "sensory": sensory,
        "recipe": recipe,
        "generated_on": date.today().isoformat(),
        "provenance": "GoodCup demo · synthetic data",
    }


# --------------------------------------------------------------------------- #
# Rendering (DESIGN.md tokens; echoes the goodcup.ph brew-sheet aesthetic)
# --------------------------------------------------------------------------- #
INK, GREEN, MUTED, RULE, CANVAS = "#191915", "#009B2A", "#6A6963", "#DDDAD3", "#F3F1ED"


def render_brew_sheet_html(sheet: dict) -> str:
    """Render the brew sheet as a self-contained styled HTML fragment."""
    r = sheet["recipe"]
    region = " · ".join(x for x in (sheet.get("region"), sheet.get("origin_country")) if x)
    tags = " ".join(
        f'<span class="bs-badge">{t}</span>'
        for t in (sheet.get("process"), sheet.get("roast_level")) if t
    )

    if sheet["flavor_notes"]:
        notes = ", ".join(sheet["flavor_notes"])
        cup = f'<span class="bs-notes">{notes}</span> — measured from {sheet["n_cuppings"]} cuppings of this lot.'
    else:
        cup = "No cuppings recorded yet for this lot, so flavour notes are not shown."

    if sheet["sensory"]:
        s = sheet["sensory"]
        cells = "".join(
            f'<div class="bs-cell"><div class="bs-k">{k}</div><div class="bs-v">{v if v is not None else "–"}</div></div>'
            for k, v in (("Acidity", s["acidity"]), ("Sweetness", s["sweetness"]), ("Body", s["body"]), ("Score", s["score"]))
        )
        sensory = f'<div class="bs-grid">{cells}</div><div class="bs-fine">Expected sensory = mean of this lot\'s cupping components (N = {s["n"]}).</div>'
    else:
        sensory = '<div class="bs-fine">No cupping data yet — expected sensory not shown.</div>'

    grinders = " · ".join(f"{k} {v}" for k, v in r["grinders"].items())
    pours = "".join(
        f'<div class="bs-pour"><div class="bs-k">{t}</div><div class="bs-pv">{label}</div><div class="bs-fine">{desc}</div></div>'
        for (t, label, desc) in r["pours"]
    )
    recipe_cells = "".join(
        f'<div class="bs-cell"><div class="bs-k">{k}</div><div class="bs-v">{v}</div></div>'
        for k, v in (("Coffee", f"{r['dose_g']} g"), ("Water", f"{r['water_g']} g"),
                     ("Temp", f"{r['temp_c']} °C"), ("Ratio", r["ratio"]))
    )

    return f"""
    <div class="brew-sheet">
      <style>
        .brew-sheet {{ background:{CANVAS}; border:1px solid {RULE}; border-radius:10px;
          padding:1.6rem 1.8rem; color:{INK}; font-family:Inter,-apple-system,sans-serif; max-width:720px; }}
        .brew-sheet .bs-eyebrow {{ font-size:.62rem; letter-spacing:.18em; color:{MUTED}; font-weight:700;
          display:flex; justify-content:space-between; border-bottom:1px solid {RULE}; padding-bottom:.5rem; }}
        .brew-sheet h2.bs-title {{ font-size:1.9rem; letter-spacing:-.03em; margin:.7rem 0 .1rem; line-height:1.02; }}
        .brew-sheet .bs-title em {{ color:{GREEN}; font-style:italic; }}
        .brew-sheet .bs-sub {{ color:{MUTED}; font-size:.8rem; margin-bottom:.9rem; }}
        .brew-sheet .bs-badge {{ font-size:.6rem; letter-spacing:.12em; font-weight:700; text-transform:uppercase;
          border:1px solid {RULE}; border-radius:5px; padding:.16rem .42rem; color:{MUTED}; }}
        .brew-sheet .bs-section {{ font-size:.62rem; letter-spacing:.16em; color:{MUTED}; font-weight:700;
          text-transform:uppercase; margin:1.05rem 0 .35rem; }}
        .brew-sheet .bs-grid {{ display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid {RULE}; border-bottom:1px solid {RULE}; }}
        .brew-sheet .bs-cell {{ padding:.55rem .6rem; border-right:1px solid {RULE}; }}
        .brew-sheet .bs-cell:last-child {{ border-right:0; }}
        .brew-sheet .bs-k {{ font-size:.58rem; letter-spacing:.1em; color:{MUTED}; text-transform:uppercase; font-weight:700; }}
        .brew-sheet .bs-v {{ font-size:1.15rem; font-weight:700; font-variant-numeric:tabular-nums; margin-top:.15rem; }}
        .brew-sheet .bs-pour {{ display:grid; grid-template-columns:64px 90px 1fr; gap:.6rem; align-items:baseline;
          padding:.4rem 0; border-bottom:1px solid {RULE}; }}
        .brew-sheet .bs-pv {{ font-weight:700; font-size:.82rem; }}
        .brew-sheet .bs-fine {{ color:{MUTED}; font-size:.7rem; }}
        .brew-sheet .bs-notes {{ color:{GREEN}; font-weight:700; }}
        .brew-sheet .bs-foot {{ display:flex; justify-content:space-between; color:{MUTED}; font-size:.62rem;
          letter-spacing:.08em; border-top:1px solid {RULE}; margin-top:1.1rem; padding-top:.55rem; text-transform:uppercase; }}
        .brew-sheet .bs-template {{ background:#F0F3EA; border:1px solid #D6DEC9; color:#3E4934; border-radius:6px;
          padding:.4rem .55rem; font-size:.66rem; margin:.35rem 0 .1rem; }}
      </style>
      <div class="bs-eyebrow"><span>GOOD CUP COFFEE · BREW GUIDE</span><span>ROASTERY BREW SHEET · V1.0</span></div>
      <h2 class="bs-title">{sheet['lot_name']}</h2>
      <div class="bs-sub">{region} &nbsp;·&nbsp; {sheet.get('varietal') or 'varietal n/a'} &nbsp; {tags}</div>

      <div class="bs-section">In the cup — from your data</div>
      <div class="bs-fine">{cup}</div>

      <div class="bs-section">Expected sensory</div>
      {sensory}

      <div class="bs-section">Recipe — starting point, dial by taste</div>
      <div class="bs-template">Recipe is a conventional starting point for {r['method']} at a {sheet['roast_level']} roast ({sheet['roast_level_basis']}), not a measured value. Adjust to taste.</div>
      <div class="bs-grid">{recipe_cells}</div>
      <div class="bs-fine" style="margin-top:.4rem">Grind {r['grind']} — {grinders}</div>

      <div class="bs-section">Pour schedule</div>
      {pours}

      <div class="bs-foot"><span>{sheet['provenance']}</span><span>{sheet['generated_on']}</span></div>
    </div>
    """
