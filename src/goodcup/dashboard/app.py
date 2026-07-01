"""GoodCup Roast Intelligence client-demo dashboard."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import DB_PATH, PHASE2_MIN_MATCHED_ROASTS
from goodcup.analysis.calibration import calibration_report
from goodcup.analysis.correlation import correlation_report
from goodcup.analysis import descriptors as descriptors_analysis
from goodcup.analysis.lot_history import repeatability_summary, require_single_temperature_unit
from goodcup.db import models
from goodcup.dashboard.experiment_demo import (
    BLIND_PROFILE_MAP,
    DEFAULT_CUP_SCORES,
    evaluate_blind_results,
)
from goodcup.knowledge import brew_sheet as brew_sheet_lib
from goodcup.research import literature as literature_lib
from goodcup.seed.generate import generate


GREEN = "#009B2A"
INK = "#191915"
MUTED = "#6A6963"
RULE = "#DDDAD3"
CANVAS = "#F3F1ED"
SURFACE = "#FCFBF8"
ORANGE = "#DE681B"


st.set_page_config(
    page_title="GoodCup Roast Intelligence",
    page_icon="☕",
    layout="wide",
    initial_sidebar_state="auto",
)


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        :root {{ color-scheme: light; }}
        .stApp {{ background: {CANVAS}; color: {INK}; }}
        html, body, [class*="css"] {{ font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
        header[data-testid="stHeader"] {{ background: transparent; height: 0; }}
        [data-testid="stToolbar"] {{ display:none !important; }}
        #MainMenu, footer {{ display: none; }}
        .block-container {{ padding: 1.35rem 2.1rem 3rem; max-width: 1500px; }}
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{ gap: 0.62rem; }}
        section[data-testid="stSidebar"] {{ background: {SURFACE}; border-right: 1px solid {RULE}; width: 232px !important; }}
        section[data-testid="stSidebar"] .block-container {{ padding: 1.75rem 1rem; }}
        section[data-testid="stSidebar"] [data-testid="stImage"] img {{ width: 76px; margin: 0.2rem auto 0.8rem; display: block; }}
        section[data-testid="stSidebar"] [role="radiogroup"] {{ gap: 0.42rem; }}
        section[data-testid="stSidebar"] [role="radiogroup"] label {{
            padding: 0.74rem 0.78rem; border-radius: 7px; font-size: 0.88rem;
            transition: background 160ms ease-out, color 160ms ease-out;
        }}
        section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{
            background: #EAF1E7; color: #086B20; box-shadow: inset 3px 0 0 {GREEN};
        }}
        input[type="radio"] {{ accent-color:{GREEN} !important; }}
        section[data-testid="stSidebar"] hr {{ border-color: {RULE}; margin: 1.2rem 0; }}
        h1 {{ font-size: 1.92rem !important; line-height: 1.08 !important; letter-spacing: -0.035em; max-width: 720px; }}
        h2 {{ font-size: 1.35rem !important; letter-spacing: -0.02em; }}
        h3 {{ font-size: 1.02rem !important; letter-spacing: -0.01em; }}
        p {{ color: {MUTED}; }}
        .workspace-bar {{ display:flex; align-items:center; justify-content:space-between; border-bottom:1px solid {RULE}; padding-bottom:0.75rem; margin-bottom:0.85rem; }}
        .workspace-name {{ color:{INK}; font-size:0.84rem; font-weight:650; }}
        .demo-chip {{ color:#0A6D22; background:#EDF5EA; border:1px solid #C8DDC3; padding:0.38rem 0.62rem; border-radius:7px; font-size:0.75rem; font-weight:650; }}
        .lede {{ font-size:0.94rem; margin-top:-0.6rem; max-width:650px; }}
        .metric-rail {{ display:grid; grid-template-columns:repeat(4,1fr); border-top:1px solid {RULE}; border-bottom:1px solid {RULE}; margin:0.75rem 0 0.7rem; }}
        .metric {{ padding:1rem 1.1rem 0.95rem; border-right:1px solid {RULE}; }}
        .metric:last-child {{ border-right:0; }}
        .metric-value {{ color:{INK}; font-size:1.72rem; line-height:1; font-weight:760; font-variant-numeric:tabular-nums; }}
        .metric-value.green {{ color:{GREEN}; }}
        .metric-label {{ color:{INK}; font-size:0.76rem; font-weight:650; margin-top:0.45rem; }}
        .metric-note {{ color:{MUTED}; font-size:0.68rem; margin-top:0.12rem; }}
        .panel {{ background:{SURFACE}; border:1px solid {RULE}; border-radius:9px; padding:1.05rem 1.15rem; margin-bottom:0.75rem; }}
        .panel-title {{ color:{INK}; font-size:1rem; font-weight:720; margin-bottom:0.22rem; }}
        .panel-copy {{ color:{MUTED}; font-size:0.76rem; margin-bottom:0.8rem; }}
        .guardrail {{ background:#F0F3EA; border:1px solid #D6DEC9; border-radius:8px; color:#3E4934; padding:0.72rem 0.88rem; font-size:0.76rem; margin:0.4rem 0 0.9rem; }}
        .insight {{ display:grid; grid-template-columns:26px 1fr; gap:0.65rem; padding:0.68rem 0; border-bottom:1px solid {RULE}; }}
        .insight:last-child {{ border-bottom:0; }}
        .insight-dot {{ width:24px; height:24px; border-radius:50%; background:#E7EFE2; color:#0A6D22; display:grid; place-items:center; font-weight:800; }}
        .insight strong {{ color:{INK}; font-size:0.78rem; display:block; line-height:1.3; }}
        .insight span {{ color:{MUTED}; font-size:0.68rem; line-height:1.35; display:block; margin-top:0.12rem; }}
        .person {{ border:1px solid {RULE}; border-radius:8px; padding:0.8rem; background:{SURFACE}; min-height:102px; }}
        .person.review {{ border-color:#F1A070; background:#FFF8F3; }}
        .person-name {{ color:{INK}; font-size:0.82rem; font-weight:700; }}
        .person-status {{ font-size:0.7rem; font-weight:700; margin-top:0.4rem; color:{GREEN}; }}
        .person.review .person-status {{ color:{ORANGE}; }}
        .person-detail {{ color:{MUTED}; font-size:0.66rem; margin-top:0.18rem; }}
        .phase-lock {{ background:#F9EFE8; border:1px solid #F0CCB2; border-radius:9px; padding:1rem; color:#70401E; font-size:0.82rem; }}
        .experiment-rail {{ display:grid; grid-template-columns:1.25fr .8fr .8fr 1fr; border:1px solid {RULE}; border-radius:9px; background:{SURFACE}; margin:1rem 0; }}
        .experiment-stat {{ padding:1rem; border-right:1px solid {RULE}; }}
        .experiment-stat:last-child {{ border-right:0; }}
        .experiment-stat strong {{ display:block; color:{INK}; font-size:.88rem; margin-top:.2rem; }}
        .experiment-stat span {{ color:{MUTED}; font-size:.68rem; }}
        .hypothesis {{ background:#ECF4E9; border:1px solid #CADDC4; border-radius:9px; padding:1rem 1.1rem; color:#2F482D; font-size:.84rem; line-height:1.5; }}
        .blind-code {{ background:{SURFACE}; border:1px solid {RULE}; border-radius:9px; padding:.85rem; margin-bottom:.55rem; }}
        .blind-number {{ font-size:1.45rem; font-weight:780; letter-spacing:.08em; color:{INK}; }}
        .blind-meta {{ color:{MUTED}; font-size:.7rem; margin-top:.2rem; }}
        .reveal {{ border-top:1px solid {RULE}; padding:.8rem 0; display:flex; justify-content:space-between; gap:1rem; }}
        .reveal strong {{ color:{INK}; font-size:.8rem; }}
        .reveal span {{ color:{MUTED}; font-size:.72rem; }}
        .decision {{ background:{INK}; color:#F8F7F2; border-radius:9px; padding:1.15rem 1.25rem; margin:.8rem 0; }}
        .decision strong {{ display:block; font-size:1rem; margin-bottom:.25rem; }}
        .decision span {{ color:#D8D6CE; font-size:.78rem; line-height:1.45; }}
        .lot-rail {{ display:grid; grid-template-columns:1.35fr repeat(4, .8fr); border-top:1px solid {RULE}; border-bottom:1px solid {RULE}; margin:.8rem 0 1rem; }}
        .lot-stat {{ padding:.9rem 1rem; border-right:1px solid {RULE}; }}
        .lot-stat:last-child {{ border-right:0; }}
        .lot-stat strong {{ display:block; color:{INK}; font-size:.9rem; margin-top:.18rem; }}
        .lot-stat span {{ color:{MUTED}; font-size:.67rem; }}
        .best-label {{ color:#087F28; background:#E8F1E4; border:1px solid #C8DDC3; border-radius:5px; padding:.18rem .38rem; font-size:.62rem; font-weight:750; }}
        .repeatability-note {{ color:{MUTED}; font-size:.7rem; line-height:1.4; margin-top:.25rem; }}
        div[data-testid="stForm"] {{ background:{SURFACE}; border:1px solid {RULE}; border-radius:9px; padding:1rem; }}
        div[data-testid="stFormSubmitButton"] button {{ background:{GREEN} !important; color:#F8FFF7 !important; border-color:{GREEN} !important; }}
        div[data-testid="stFormSubmitButton"] button * {{ color:#F8FFF7 !important; }}
        .stButton > button, .stDownloadButton > button {{ border-radius:7px; border:1px solid {RULE}; font-size:0.78rem; font-weight:650; min-height:2.4rem; }}
        .stButton > button {{ background:{GREEN} !important; color:#F8FFF7 !important; border-color:{GREEN} !important; }}
        .stButton > button * {{ color:#F8FFF7 !important; }}
        .stButton > button:hover {{ background:#087F28 !important; color:#F8FFF7 !important; }}
        .stSelectbox label, .stFileUploader label {{ font-size:0.74rem; color:{MUTED}; font-weight:650; }}
        [data-testid="stDataFrame"] {{ border:1px solid {RULE}; border-radius:8px; overflow:hidden; }}
        @media (max-width: 900px) {{
          .metric-rail {{ grid-template-columns:1fr 1fr; }}
          .metric:nth-child(2) {{ border-right:0; }}
          .metric:nth-child(-n+2) {{ border-bottom:1px solid {RULE}; }}
          .block-container {{ padding:1.25rem 1rem 2rem; }}
          .experiment-rail {{ grid-template-columns:1fr 1fr; }}
          .experiment-stat:nth-child(2) {{ border-right:0; }}
          .experiment-stat:nth-child(-n+2) {{ border-bottom:1px solid {RULE}; }}
          .lot-rail {{ grid-template-columns:1fr 1fr; }}
          .lot-stat {{ border-bottom:1px solid {RULE}; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def ensure_demo() -> None:
    # Apply the schema idempotently first. Every statement is CREATE ... IF NOT
    # EXISTS (or DROP+CREATE for views/triggers), so this is a safe, data-preserving
    # migration that adds any newly-introduced tables to an existing demo database.
    conn = models.init_db(DB_PATH, reset=False)
    count = conn.execute("SELECT COUNT(*) FROM roasts").fetchone()[0]
    conn.close()
    if count == 0:
        generate("full", DB_PATH)
    # descriptors are a rebuildable derived table; ensure they exist for the demo
    conn = models.connect(DB_PATH)
    try:
        if conn.execute("SELECT COUNT(*) FROM descriptors").fetchone()[0] == 0:
            descriptors_analysis.rebuild_descriptors(conn)
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def summary_data(db_mtime: float) -> dict:
    conn = models.connect(DB_PATH)
    try:
        counts = {
            "greens": conn.execute("SELECT COUNT(*) FROM greens").fetchone()[0],
            "roasts": conn.execute("SELECT COUNT(*) FROM roasts").fetchone()[0],
            "cuppings": conn.execute("SELECT COUNT(*) FROM cuppings").fetchone()[0],
            "matched": models.count_matched_roasts(conn),
        }
        return counts
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def associations(db_mtime: float, machine: str, process: str) -> pd.DataFrame:
    conn = models.connect(DB_PATH)
    try:
        report = correlation_report(conn, stratify=False)
        df = report.overall.to_frame()
        if machine != "All machines" or process != "All processes":
            base = models.read_sql(conn, "SELECT * FROM matched_roasts")
            if machine != "All machines":
                base = base[base["machine_id"] == machine]
            if process != "All processes":
                base = base[base["process"] == process]
            from goodcup.analysis.correlation import _scan, DEFAULT_METRICS
            df = _scan(base, DEFAULT_METRICS, "mean_total_score", "Filtered roasts").to_frame()
        return df
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def roast_table(db_mtime: float) -> pd.DataFrame:
    conn = models.connect(DB_PATH)
    try:
        return models.read_sql(conn, """
            SELECT r.roast_id, r.roast_ref, r.roast_date, r.machine_id, r.roaster_name,
                   r.dtr_pct, r.total_time_s, r.drop_temp, r.green_id,
                   r.temp_unit, r.curve_available, r.ambient_temp_c, r.ambient_humidity_pct,
                   g.lot_name, g.origin_country, g.process,
                   m.mean_total_score, m.n_cuppings
            FROM roasts r
            JOIN greens g ON g.green_id = r.green_id
            LEFT JOIN matched_roasts m ON m.roast_id = r.roast_id
            ORDER BY r.roast_id
        """)
    finally:
        conn.close()


@st.cache_data(show_spinner=False)
def lot_bundle(db_mtime: float, green_id: int) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    conn = models.connect(DB_PATH)
    try:
        green_row = conn.execute("SELECT * FROM greens WHERE green_id = ?", (green_id,)).fetchone()
        green = dict(green_row) if green_row else {}
        history = models.read_sql(conn, """
            SELECT r.roast_id, r.roast_ref, r.roast_date, r.roaster_name, r.machine_id,
                   r.temp_unit, r.curve_available, r.charge_temp, r.drop_temp,
                   r.total_time_s, r.dtr_pct, r.dry_end_time_s, r.fc_start_time_s,
                   r.ambient_temp_c, r.ambient_humidity_pct,
                   m.mean_total_score, m.n_cuppings
            FROM roasts r
            LEFT JOIN matched_roasts m ON m.roast_id = r.roast_id
            WHERE r.green_id = ?
            ORDER BY r.roast_date, r.roast_id
        """, [green_id])
        curves = models.read_sql(conn, """
            SELECT rc.roast_id, r.roast_ref, r.temp_unit, rc.time_s,
                   rc.bean_temp, rc.env_temp, rc.ror
            FROM roast_curves rc
            JOIN roasts r ON r.roast_id = rc.roast_id
            WHERE r.green_id = ?
            ORDER BY rc.roast_id, rc.time_s
        """, [green_id])
        return green, history, curves
    finally:
        conn.close()


def workspace_header() -> None:
    st.markdown(
        """<div class="workspace-bar"><span class="workspace-name">GoodCup R&amp;D · Demo workspace</span><span class="demo-chip">● Synthetic data</span></div>""",
        unsafe_allow_html=True,
    )


def metric_rail(s: dict) -> None:
    st.markdown(
        f"""
        <div class="metric-rail">
          <div class="metric"><div class="metric-value">{s['matched']}</div><div class="metric-label">Matched roasts</div><div class="metric-note">with cupping scores</div></div>
          <div class="metric"><div class="metric-value">{s['greens']}</div><div class="metric-label">Green lots</div><div class="metric-note">unique demo lots</div></div>
          <div class="metric"><div class="metric-value">{s['cuppings']}</div><div class="metric-label">Cuppings</div><div class="metric-note">across four cuppers</div></div>
          <div class="metric"><div class="metric-value green">{s['matched']} / {PHASE2_MIN_MATCHED_ROASTS}</div><div class="metric-label">Recommendation gate</div><div class="metric-note">production locked · demo only</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def forest_figure(df: pd.DataFrame) -> go.Figure:
    clean = df.dropna(subset=["r"]).head(7).iloc[::-1]
    fig = go.Figure()
    fig.add_vline(x=0, line_width=1, line_dash="dot", line_color="#8C8A84")
    fig.add_trace(go.Scatter(
        x=clean["r"], y=clean["label"], mode="markers",
        marker=dict(color=GREEN, size=10, line=dict(color="white", width=1)),
        error_x=dict(
            type="data", symmetric=False,
            array=(clean["ci_high"] - clean["r"]).clip(lower=0),
            arrayminus=(clean["r"] - clean["ci_low"]).clip(lower=0),
            color="#55A463", thickness=1.4, width=4,
        ),
        customdata=np.stack([clean["n"], clean["p_raw"], clean["p_fdr"]], axis=-1),
        hovertemplate="<b>%{y}</b><br>r = %{x:.2f}<br>N = %{customdata[0]:.0f}<br>raw p = %{customdata[1]:.3g}<br>FDR p = %{customdata[2]:.3g}<extra></extra>",
    ))
    fig.update_layout(
        height=285, margin=dict(l=5, r=15, t=10, b=30),
        paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, showlegend=False,
        font=dict(family="Inter, sans-serif", color=INK, size=12),
        xaxis=dict(title="Lower association          Effect size (r)          Higher association", range=[-0.85, 0.85], gridcolor="#ECE9E2", zeroline=False),
        yaxis=dict(title=None, tickfont=dict(size=11)),
    )
    return fig


def insight_html(df: pd.DataFrame) -> str:
    items = []
    for row in df.dropna(subset=["r"]).head(4).itertuples():
        direction = "higher" if row.r > 0 else "lower"
        relation = "higher" if row.r > 0 else "lower"
        items.append(
            f'<div class="insight"><div class="insight-dot">↗</div><div><strong>{row.label} is associated with {relation} cup scores.</strong><span>r = {row.r:.2f}, 95% CI {row.ci_low:.2f} to {row.ci_high:.2f}, N = {row.n}, FDR p = {row.p_fdr:.3g}. Treat this as a test-roast hypothesis.</span></div></div>'
        )
    return "".join(items)


def curve_figure(roast_id: int) -> go.Figure:
    conn = models.connect(DB_PATH)
    try:
        curve = models.read_sql(conn, "SELECT time_s, bean_temp, env_temp, ror FROM roast_curves WHERE roast_id=? ORDER BY time_s", [roast_id])
        roast = conn.execute("SELECT * FROM roasts WHERE roast_id=?", (roast_id,)).fetchone()
    finally:
        conn.close()
    unit = str(roast["temp_unit"] or "").upper() if roast else ""
    if unit not in {"C", "F"}:
        raise ValueError("This roast has no valid temperature unit, so its curve cannot be shown safely")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.time_s / 60, y=curve.bean_temp, name=f"BT (°{unit})", line=dict(color=INK, width=2.2), hovertemplate=f"%{{x:.1f}} min · %{{y:.1f}}°{unit}<extra>BT</extra>"))
    fig.add_trace(go.Scatter(x=curve.time_s / 60, y=curve.env_temp, name=f"ET (°{unit})", line=dict(color="#9B7148", width=1.4, dash="dot"), hovertemplate=f"%{{x:.1f}} min · %{{y:.1f}}°{unit}<extra>ET</extra>"))
    fig.add_trace(go.Scatter(x=curve.time_s / 60, y=curve.ror, name=f"RoR (°{unit}/min)", yaxis="y2", line=dict(color=GREEN, width=1.6), hovertemplate=f"%{{x:.1f}} min · %{{y:.1f}}°{unit}/min<extra>RoR</extra>"))
    for label, key in [("Dry end", "dry_end_time_s"), ("First crack", "fc_start_time_s"), ("Drop", "drop_time_s")]:
        value = roast[key] if roast else None
        if value is not None:
            fig.add_vline(x=value / 60, line_width=1, line_dash="dot", line_color="#88857F", annotation_text=label, annotation_position="top")
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=35, b=25), paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        hovermode="x unified", legend=dict(orientation="h", y=1.16, x=0),
        font=dict(family="Inter, sans-serif", color=INK, size=11),
        xaxis=dict(title="Time from charge (min)", gridcolor="#EEEAE3"),
        yaxis=dict(title=f"Temperature (°{unit})", gridcolor="#EEEAE3"),
        yaxis2=dict(title=f"RoR (°{unit}/min)", overlaying="y", side="right", showgrid=False, color=GREEN),
    )
    return fig


def lot_score_figure(history: pd.DataFrame) -> go.Figure:
    scored = history.dropna(subset=["mean_total_score"]).copy()
    scored["sequence"] = range(1, len(scored) + 1)
    best_idx = scored["mean_total_score"].idxmax() if not scored.empty else None
    colors = [GREEN if idx == best_idx else "#7A7871" for idx in scored.index]
    sizes = [12 if idx == best_idx else 8 for idx in scored.index]
    fig = go.Figure(go.Scatter(
        x=scored["sequence"], y=scored["mean_total_score"], mode="lines+markers+text",
        line=dict(color="#AAA69D", width=1.5), marker=dict(color=colors, size=sizes),
        text=scored["roast_ref"], textposition="top center",
        customdata=np.stack([scored["roast_date"], scored["dtr_pct"], scored["n_cuppings"]], axis=-1),
        hovertemplate="<b>%{text}</b><br>Score %{y:.2f}<br>Date %{customdata[0]}<br>DTR %{customdata[1]:.1f}%<br>N cuppings %{customdata[2]:.0f}<extra></extra>",
    ))
    fig.update_layout(
        height=285, margin=dict(l=10, r=10, t=20, b=30), paper_bgcolor=CANVAS, plot_bgcolor=SURFACE,
        font=dict(family="Inter, sans-serif", color=INK, size=11), showlegend=False,
        xaxis=dict(title="Roast sequence", dtick=1, gridcolor="#EEEAE3"),
        yaxis=dict(title="Mean cup score", gridcolor="#EEEAE3"),
    )
    return fig


def lot_overlay_figure(history: pd.DataFrame, curves: pd.DataFrame, selected: list[str], show_et: bool, show_ror: bool) -> go.Figure:
    chosen = history[history["roast_ref"].isin(selected)].copy()
    unit = require_single_temperature_unit(chosen)
    best_ref = None
    if not chosen.dropna(subset=["mean_total_score"]).empty:
        best_ref = chosen.loc[chosen["mean_total_score"].idxmax(), "roast_ref"]
    palette = [GREEN, "#326B9B", "#D17B28", "#7A5C9E", "#6E6B65"]
    fig = go.Figure()
    for color, row in zip(palette, chosen.itertuples()):
        c = curves[curves["roast_id"] == row.roast_id]
        if c.empty:
            continue
        label = f"{row.roast_ref}{' · BEST' if row.roast_ref == best_ref else ''}"
        fig.add_trace(go.Scatter(
            x=c.time_s / 60, y=c.bean_temp, name=f"{label} BT",
            line=dict(color=color, width=3 if row.roast_ref == best_ref else 1.8),
            hovertemplate=f"<b>{row.roast_ref} BT</b><br>%{{x:.1f}} min · %{{y:.1f}}°{unit}<extra></extra>",
        ))
        if show_et:
            fig.add_trace(go.Scatter(
                x=c.time_s / 60, y=c.env_temp, name=f"{row.roast_ref} ET",
                line=dict(color=color, width=1, dash="dot"), opacity=.7,
                hovertemplate=f"<b>{row.roast_ref} ET</b><br>%{{x:.1f}} min · %{{y:.1f}}°{unit}<extra></extra>",
            ))
        if show_ror:
            fig.add_trace(go.Scatter(
                x=c.time_s / 60, y=c.ror, name=f"{row.roast_ref} RoR", yaxis="y2",
                line=dict(color=color, width=1.3, dash="dash"),
                hovertemplate=f"<b>{row.roast_ref} RoR</b><br>%{{x:.1f}} min · %{{y:.1f}}°{unit}/min<extra></extra>",
            ))
    fig.update_layout(
        height=430, margin=dict(l=10, r=15, t=35, b=35), paper_bgcolor=CANVAS, plot_bgcolor=SURFACE,
        hovermode="x unified", font=dict(family="Inter, sans-serif", color=INK, size=11),
        legend=dict(orientation="h", y=1.14, x=0),
        xaxis=dict(title="Time from charge (min)", gridcolor="#EEEAE3"),
        yaxis=dict(title=f"Temperature (°{unit})", gridcolor="#EEEAE3"),
        yaxis2=dict(title=f"RoR (°{unit}/min)", overlaying="y", side="right", showgrid=False, visible=show_ror, color=GREEN),
    )
    return fig


def filters(roasts: pd.DataFrame) -> tuple[str, str]:
    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        machine = st.selectbox("Machine", ["All machines"] + sorted(roasts.machine_id.dropna().unique().tolist()))
    with c2:
        process = st.selectbox("Process", ["All processes"] + sorted(roasts.process.dropna().unique().tolist()))
    with c3:
        st.caption("Filters recompute the visible association scan. Thin strata remain exploratory.")
    return machine, process


def overview(s: dict, roasts: pd.DataFrame, mtime: float) -> None:
    st.title("See what your roasting data is actually saying.")
    st.markdown('<p class="lede">Local-first evidence for better decisions in the lab and on the roast floor.</p>', unsafe_allow_html=True)
    st.button("Import roast data", type="primary", on_click=lambda: st.session_state.update(nav_page="Data library"))
    metric_rail(s)
    machine, process = filters(roasts)
    df = associations(mtime, machine, process)
    n_visible = int(df["n"].max()) if not df.empty else 0
    st.markdown(f'<div class="guardrail"><strong>Exploratory analysis.</strong> Every point shows effect size, 95% CI, N, and FDR-adjusted p. The filtered scan currently uses up to N = {n_visible}. Mixed machines, origins, and processes can confound single-variable associations.</div>', unsafe_allow_html=True)
    left, right = st.columns([1.45, 1], gap="medium")
    with left:
        st.markdown('<div class="panel-title">Quality associations</div><div class="panel-copy">Ranked by effect size, with 95% confidence intervals. Hover for raw and adjusted p-values.</div>', unsafe_allow_html=True)
        st.plotly_chart(forest_figure(df), width="stretch", config={"displayModeBar": False})
    with right:
        st.markdown('<div class="panel-title">What deserves a test roast</div><div class="panel-copy">These are correlational signals, not causal conclusions.</div>', unsafe_allow_html=True)
        st.markdown(insight_html(df), unsafe_allow_html=True)
        st.button("Design controlled test", on_click=lambda: st.session_state.update(nav_page="Experiment Lab"))
    st.markdown("### One roast, end to end")
    options = roasts.dropna(subset=["mean_total_score"]).sort_values("mean_total_score", ascending=False)
    labels = {f"{r.roast_ref} · {r.lot_name} · {r.mean_total_score:.1f}": int(r.roast_id) for r in options.itertuples()}
    selected = st.selectbox("Roast profile", list(labels), label_visibility="collapsed")
    st.plotly_chart(curve_figure(labels[selected]), width="stretch", config={"displayModeBar": False})


def roast_insights(roasts: pd.DataFrame, mtime: float) -> None:
    st.title("Roast insights")
    st.markdown('<p class="lede">Move from a ranked association to the roasts behind it.</p>', unsafe_allow_html=True)
    machine, process = filters(roasts)
    df = associations(mtime, machine, process)
    st.plotly_chart(forest_figure(df), width="stretch", config={"displayModeBar": False})
    table = df[["label", "n", "r", "ci_low", "ci_high", "p_raw", "p_fdr", "effect", "small_sample"]].copy()
    table.columns = ["Variable", "N", "Effect r", "CI low", "CI high", "Raw p", "FDR p", "Magnitude", "Small sample"]
    st.dataframe(table, width="stretch", hide_index=True, column_config={"Effect r": st.column_config.NumberColumn(format="%.2f"), "Raw p": st.column_config.NumberColumn(format="%.4f"), "FDR p": st.column_config.NumberColumn(format="%.4f")})


def lot_history_page(roasts: pd.DataFrame, mtime: float) -> None:
    st.title("Lot history")
    st.markdown('<p class="lede">See whether repeated roasts are learning, drifting, or simply repeating noise.</p>', unsafe_allow_html=True)
    counts = roasts.groupby(["green_id", "lot_name"], as_index=False).size().sort_values(["size", "lot_name"], ascending=[False, True])
    lot_options = {f"{r.lot_name} · {r.size} roasts": int(r.green_id) for r in counts.itertuples()}
    selected_lot = st.selectbox("Green lot", list(lot_options))
    green, history, curves = lot_bundle(mtime, lot_options[selected_lot])
    repeat = repeatability_summary(history)

    best = history.dropna(subset=["mean_total_score"]).sort_values("mean_total_score", ascending=False).head(1)
    best_score = f"{best.iloc[0].mean_total_score:.2f}" if not best.empty else "Not scored"
    unit_values = sorted(history.temp_unit.dropna().unique().tolist())
    unit_label = ", ".join(unit_values) if unit_values else "Missing"
    score_sd = "–" if repeat["score_sd"] is None else f"{repeat['score_sd']:.2f}"
    st.markdown(
        f"""
        <div class="lot-rail">
          <div class="lot-stat"><span>Green lot</span><strong>{green.get('lot_name', 'Unknown')}</strong><span>{green.get('origin_country') or 'Origin not recorded'} · {green.get('process') or 'Process not recorded'}</span></div>
          <div class="lot-stat"><span>Roasts</span><strong>{repeat['n_roasts']}</strong><span>{repeat['curve_coverage']:.0%} curve coverage</span></div>
          <div class="lot-stat"><span>Best score</span><strong style="color:{GREEN}">{best_score}</strong><span>mean panel score</span></div>
          <div class="lot-stat"><span>Score spread</span><strong>{score_sd}</strong><span>standard deviation</span></div>
          <div class="lot-stat"><span>Temperature unit</span><strong>°{unit_label}</strong><span>overlay safety check</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left, right = st.columns([1.55, 1], gap="large")
    with left:
        st.markdown("### Score trend")
        st.caption("One point per roast. The best scored roast is highlighted in green; every mean retains its cupping N in the hover detail.")
        if history["mean_total_score"].notna().sum() >= 2:
            st.plotly_chart(lot_score_figure(history), width="stretch", config={"displayModeBar": False})
        else:
            st.info("This lot needs at least two scored roasts before a trend can be shown.")
    with right:
        st.markdown("### Repeatability")
        st.markdown(f'<div class="hypothesis"><strong>{repeat["status"]}</strong><br>Spread describes repeatability, not quality. A tight low score is still low; a high score with wide spread may be hard to reproduce.</div>', unsafe_allow_html=True)
        rep_rows = pd.DataFrame([
            {"Measure": "Cup score SD", "Spread": repeat["score_sd"]},
            {"Measure": "DTR SD (percentage points)", "Spread": repeat["dtr_sd"]},
            {"Measure": f"Drop temperature SD (°{unit_label})", "Spread": repeat["drop_temp_sd"]},
            {"Measure": "Total time SD (seconds)", "Spread": repeat["total_time_sd"]},
        ])
        st.dataframe(rep_rows, width="stretch", hide_index=True, column_config={"Spread": st.column_config.NumberColumn(format="%.2f")})

    st.markdown("### Profile comparison")
    st.caption("Overlay up to five roasts from the same lot. The highest-scoring selected roast is emphasized; mixed °C/°F data is refused rather than converted silently.")
    curve_history = history[(history["curve_available"] == 1) & history["roast_ref"].notna()].copy()
    defaults = curve_history.sort_values("mean_total_score", ascending=False, na_position="last").roast_ref.head(3).tolist()
    controls = st.columns([2.2, .7, .7])
    with controls[0]:
        selected_refs = st.multiselect("Roasts to overlay", curve_history.roast_ref.tolist(), default=defaults, max_selections=5)
    with controls[1]:
        show_et = st.toggle("Show ET", value=False)
    with controls[2]:
        show_ror = st.toggle("Show RoR", value=True)
    if not selected_refs:
        st.info("Select at least one roast with curve data.")
    else:
        try:
            st.plotly_chart(lot_overlay_figure(history, curves, selected_refs, show_et, show_ror), width="stretch", config={"displayModeBar": False})
        except ValueError as exc:
            st.error(str(exc))

    selected_rows = history[history["roast_ref"].isin(selected_refs)].copy()
    if not selected_rows.empty:
        best_ref = selected_rows.loc[selected_rows["mean_total_score"].idxmax(), "roast_ref"] if selected_rows["mean_total_score"].notna().any() else None
        selected_rows["Result"] = selected_rows["roast_ref"].apply(lambda x: "BEST" if x == best_ref else "")
        display = selected_rows[["Result", "roast_ref", "roast_date", "machine_id", "charge_temp", "drop_temp", "dtr_pct", "total_time_s", "mean_total_score", "n_cuppings"]]
        display.columns = ["", "Roast", "Date", "Machine", "Charge", "Drop", "DTR %", "Time (s)", "Avg score", "N cups"]
        st.dataframe(display, width="stretch", hide_index=True, column_config={"Avg score": st.column_config.NumberColumn(format="%.2f"), "DTR %": st.column_config.NumberColumn(format="%.1f")})

    ambient = history.dropna(subset=["ambient_humidity_pct", "ambient_temp_c", "mean_total_score"])
    if len(ambient) >= 3:
        with st.expander("Ambient conditions, exploratory view"):
            st.caption("This view helps spot hypotheses. It does not establish that humidity or room temperature caused a score change.")
            ambient_fig = go.Figure(go.Scatter(
                x=ambient.ambient_humidity_pct, y=ambient.mean_total_score, mode="markers+text",
                text=ambient.roast_ref, textposition="top center",
                marker=dict(size=11, color=ambient.ambient_temp_c, colorscale="YlGn", colorbar=dict(title="Ambient °C"), line=dict(color="white", width=1)),
                hovertemplate="<b>%{text}</b><br>Humidity %{x:.1f}%<br>Score %{y:.2f}<extra></extra>",
            ))
            ambient_fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=30), paper_bgcolor=CANVAS, plot_bgcolor=SURFACE, xaxis_title="Ambient humidity (%)", yaxis_title="Mean cup score", font=dict(family="Inter, sans-serif", color=INK))
            st.plotly_chart(ambient_fig, width="stretch", config={"displayModeBar": False})


def calibration_page(mtime: float) -> None:
    st.title("Cupper calibration")
    st.markdown('<p class="lede">See who is aligned with the panel and where a calibration conversation may help.</p>', unsafe_allow_html=True)
    conn = models.connect(DB_PATH)
    try:
        status, detail = calibration_report(conn)
    finally:
        conn.close()
    cols = st.columns(max(1, len(status)))
    for col, row in zip(cols, status.itertuples()):
        cls = "person review" if row.status == "Review" else "person"
        with col:
            st.markdown(f'<div class="{cls}"><div class="person-name">{row.cupper}</div><div class="person-status">{row.status}</div><div class="person-detail">Mean deviation {row.mean_deviation:+.2f}<br>95% CI {row.ci_low:+.2f} to {row.ci_high:+.2f}<br>N = {row.n}</div></div>', unsafe_allow_html=True)
    fig = go.Figure()
    for cupper, g in detail.groupby("cupper_name"):
        trend = g.groupby("session_order", as_index=False).deviation.mean()
        fig.add_trace(go.Scatter(x=trend.session_order, y=trend.deviation, mode="lines+markers", name=cupper, line=dict(width=2)))
    fig.add_hline(y=0, line_color="#8B8882", line_dash="dot")
    fig.update_layout(height=390, margin=dict(l=10, r=10, t=35, b=30), paper_bgcolor=CANVAS, plot_bgcolor=SURFACE, font=dict(family="Inter, sans-serif", color=INK), xaxis_title="Cupping session", yaxis_title="Score deviation from panel median", legend=dict(orientation="h", y=1.15), hovermode="x unified")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    st.caption("A review flag requires a practically meaningful mean deviation and a 95% confidence interval that excludes zero. It is a prompt to recalibrate, not a judgment of palate.")


def experiment_lab() -> None:
    st.title("Experiment Lab")
    st.markdown('<p class="lede">Turn an observed association into a controlled roast question the team can actually answer.</p>', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="experiment-rail">
          <div class="experiment-stat"><span>Active trial</span><strong>EXP-006 · DTR boundary test</strong></div>
          <div class="experiment-stat"><span>Green lot</span><strong>Huila Pink Bourbon</strong></div>
          <div class="experiment-stat"><span>Blind cups</span><strong>9 across 3 profiles</strong></div>
          <div class="experiment-stat"><span>Status</span><strong style="color:#087F28">Ready to cup</strong></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    design_tab, blind_tab, decision_tab = st.tabs(["1 · Design", "2 · Blind cupping", "3 · Decision"])

    with design_tab:
        st.markdown('<div class="hypothesis"><strong>Hypothesis</strong><br>Within this green and machine, extending DTR from the current 18.2% toward 20.0% is associated with a higher blind cupping score without reducing clarity. This trial changes development time only; it does not assume the historical association is causal.</div>', unsafe_allow_html=True)
        st.write("")
        profiles = pd.DataFrame([
            {"Profile": "Control", "Charge °C": 201, "Dry end": "5:04", "First crack": "8:06", "Drop": "9:54", "DTR %": 18.2, "Replicated cups": 3},
            {"Profile": "Treatment A", "Charge °C": 201, "Dry end": "5:04", "First crack": "8:06", "Drop": "10:08", "DTR %": 20.0, "Replicated cups": 3},
            {"Profile": "Treatment B", "Charge °C": 201, "Dry end": "5:04", "First crack": "8:06", "Drop": "10:21", "DTR %": 21.7, "Replicated cups": 3},
        ])
        st.dataframe(profiles, width="stretch", hide_index=True)
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.markdown("#### Held constant")
            st.markdown("Green lot · 1 kg batch · Probat P12 · charge temperature · drying phase · cupping protocol · three replicated cups")
        with c2:
            st.markdown("#### Success rule")
            st.markdown("A directional lead of at least 0.5 points advances to a confirmation roast. One trial never changes the production standard by itself.")
        with st.expander("Plan another experiment"):
            with st.form("new_experiment"):
                name = st.text_input("Question", "Does a gentler post-crack RoR preserve floral clarity?")
                variable = st.selectbox("Variable to change", ["Development time", "Post-crack RoR", "Charge temperature", "Drop temperature"])
                success = st.text_input("Success rule", "Blind score lead ≥ 0.5 with no clarity loss")
                if st.form_submit_button("Save experiment draft"):
                    st.session_state["draft_experiment"] = {"name": name, "variable": variable, "success": success}
            if st.session_state.get("draft_experiment"):
                st.success("Draft saved in this demo session. Production would persist the protocol and assign roast IDs.")

    with blind_tab:
        st.markdown("#### Score without knowing the profile")
        st.caption("Each code represents three replicated cups. Profile identities stay hidden until the panel submits all scores.")
        with st.form("blind_cupping"):
            score_values: dict[str, list[float]] = {}
            descriptors: dict[str, str] = {}
            cols = st.columns(3)
            descriptor_defaults = {"314": "caramel, orange, clean", "728": "red apple, floral, panela", "561": "cocoa, citrus, round"}
            for col, code in zip(cols, ["314", "728", "561"]):
                with col:
                    st.markdown(f'<div class="blind-code"><div class="blind-number">{code}</div><div class="blind-meta">3 cups · randomized position · identity locked</div></div>', unsafe_allow_html=True)
                    score_values[code] = [
                        st.number_input(f"Cup {i + 1}", min_value=0.0, max_value=100.0, value=float(DEFAULT_CUP_SCORES[code][i]), step=0.25, key=f"{code}_{i}")
                        for i in range(3)
                    ]
                    descriptors[code] = st.text_input("Descriptors", descriptor_defaults[code], key=f"desc_{code}")
            submitted = st.form_submit_button("Submit panel and reveal profiles")
            if submitted:
                st.session_state["experiment_result"] = evaluate_blind_results(score_values)
                st.session_state["experiment_descriptors"] = descriptors
        if st.session_state.get("experiment_result"):
            result = st.session_state["experiment_result"]
            st.success("Panel recorded. Blind identities are now unlocked for this demo session.")
            for row in result["ranking"]:
                st.markdown(f'<div class="reveal"><strong>{row["blind_code"]} · {row["profile"]}</strong><span>Mean {row["mean_score"]:.2f} · spread {row["spread"]:.2f} · N = {row["n"]}</span></div>', unsafe_allow_html=True)

    with decision_tab:
        result = st.session_state.get("experiment_result")
        if result is None:
            st.markdown('<div class="phase-lock"><strong>Decision locked.</strong> Submit the blind panel first. The profile mapping is deliberately unavailable until scoring is complete.</div>', unsafe_allow_html=True)
        else:
            winner = result["winner"]
            st.markdown(f'<div class="decision"><strong>{winner["profile"]} leads this trial by {result["margin"]:.2f} points.</strong><span>{result["decision"]}</span></div>', unsafe_allow_html=True)
            decision_rows = pd.DataFrame(result["ranking"])[["profile", "n", "mean_score", "spread"]]
            decision_rows.columns = ["Revealed profile", "N cups", "Mean score", "Within-profile spread"]
            st.dataframe(decision_rows, width="stretch", hide_index=True)
            st.markdown("#### Decision record")
            d1, d2 = st.columns(2)
            with d1:
                next_action = st.selectbox("Next action", ["Schedule confirmation roast", "Repeat this comparison", "Stop this hypothesis"])
            with d2:
                owner = st.text_input("Owner", "Head Roaster")
            note = st.text_area("R&D note", "Treatment A showed the clearest fruit expression. Confirm on a fresh roast day before changing the production standard.")
            if st.button("Record next decision"):
                import json as _json
                from datetime import date as _date
                decision_text = f"{next_action}. {result['decision']} {note}".strip()
                conn = models.connect(DB_PATH)
                try:
                    models.upsert_experiment(conn, {
                        "created_at": _date.today().isoformat(),
                        "title": "EXP-006 · DTR boundary test",
                        "hypothesis": "Within this green and machine, extending DTR toward 20.0% is associated with a higher blind cupping score.",
                        "variable": "Development time",
                        "success_rule": "Blind score lead >= 0.5 with no clarity loss",
                        "status": "decided",
                        "blind_results": _json.dumps(result["ranking"]),
                        "decision": decision_text,
                        "owner": owner,
                        "source_hash": f"exp006-{_date.today().isoformat()}-{winner['profile']}",
                    })
                finally:
                    conn.close()
                st.success("Decision recorded to the durable log. See it on the Flavor & knowledge page.")


def flavor_knowledge_page(roasts: pd.DataFrame, mtime: float) -> None:
    st.title("Flavor & knowledge")
    st.markdown('<p class="lede">Turn tasting notes, decisions, and published science into memory the team can query.</p>', unsafe_allow_html=True)
    conn = models.connect(DB_PATH)
    try:
        freq = descriptors_analysis.descriptor_frequency(conn, by="process")
        assoc = descriptors_analysis.descriptor_score_association(conn)
        experiments = models.list_experiments(conn)
        cached_refs = models.list_references(conn)
    finally:
        conn.close()

    left, right = st.columns([1, 1], gap="large")
    with left:
        st.markdown("### Flavor map")
        st.caption("Descriptor mentions mapped onto the 2016 WCR/SCA flavor wheel, by process. Unmapped terms are kept but not charted.")
        if not freq.empty:
            pivot = freq.pivot_table(index="wheel_category_l1", columns="process", values="n", fill_value=0)
            fig = go.Figure()
            for proc in pivot.columns:
                fig.add_trace(go.Bar(name=proc, y=pivot.index, x=pivot[proc], orientation="h"))
            fig.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=10, b=25), paper_bgcolor=CANVAS, plot_bgcolor=SURFACE, font=dict(family="Inter, sans-serif", color=INK, size=11), legend=dict(orientation="h", y=1.14), xaxis_title="Descriptor mentions")
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    with right:
        st.markdown("### Does a flavor family track cup score?")
        st.caption("Roast-level association between a flavor family being present and mean cup score. Correlational, guardrailed — a hypothesis to test, not a cause.")
        if assoc.empty:
            st.info("Not enough descriptor variety yet to test associations.")
        else:
            table = assoc[["category", "n", "n_present", "r", "ci_low", "ci_high", "p_raw", "p_fdr", "effect"]].copy()
            table.columns = ["Flavor family", "N", "Present", "Effect r", "CI low", "CI high", "Raw p", "FDR p", "Magnitude"]
            st.dataframe(table, width="stretch", hide_index=True, column_config={"Effect r": st.column_config.NumberColumn(format="%.2f"), "Raw p": st.column_config.NumberColumn(format="%.3f"), "FDR p": st.column_config.NumberColumn(format="%.3f")})

    st.markdown("### Decision log")
    st.caption("Durable experiment decisions — institutional memory that outlasts any single roaster.")
    if experiments.empty:
        st.info("No decisions recorded yet. Run a trial in the Experiment Lab and record its decision to start the log.")
    else:
        cols = [c for c in ["created_at", "title", "variable", "decision", "owner"] if c in experiments.columns]
        st.dataframe(experiments[cols], width="stretch", hide_index=True)

    st.markdown("### Literature")
    st.caption("Pull published science behind a hypothesis from free scholarly APIs and cache it locally. The online search is the only network step; saved papers stay available offline.")
    with st.form("lit_search"):
        c1, c2 = st.columns([3, 1])
        with c1:
            query = st.text_input("Search papers", "development time ratio coffee cupping score", label_visibility="collapsed")
        with c2:
            source = st.selectbox("Source", ["crossref", "semantic_scholar", "arxiv"], label_visibility="collapsed")
        searched = st.form_submit_button("Search & cache")
    if searched and query.strip():
        try:
            papers = literature_lib.search_papers(query, source=source, limit=6)
            conn = models.connect(DB_PATH)
            try:
                literature_lib.save_papers(conn, papers, query=query)
                cached_refs = models.list_references(conn)
            finally:
                conn.close()
            st.success(f"Found and cached {len(papers)} papers for “{query}”.")
        except literature_lib.LiteratureUnavailable:
            st.warning("No network right now — showing papers already cached locally.")
    if cached_refs.empty:
        st.info("No cached references yet.")
    else:
        for row in cached_refs.head(12).itertuples():
            meta = " · ".join(str(x) for x in (row.authors, row.year, row.venue) if x and str(x) != "None")
            link = f'<a href="{row.url}" target="_blank">{row.title}</a>' if row.url else row.title
            st.markdown(f'<div class="reveal"><strong>{link}</strong><span>{meta} · via {row.source_api}</span></div>', unsafe_allow_html=True)


def brew_sheet_page(roasts: pd.DataFrame) -> None:
    st.title("Brew sheet")
    st.markdown('<p class="lede">The customer-facing end of the same chain: lot facts and cup notes from your data, with a starting recipe to dial in.</p>', unsafe_allow_html=True)
    lots = roasts.groupby(["green_id", "lot_name"], as_index=False).size().sort_values("lot_name")
    lot_options = {r.lot_name: int(r.green_id) for r in lots.itertuples()}
    c1, c2 = st.columns([2, 1])
    with c1:
        lot = st.selectbox("Green lot", list(lot_options))
    with c2:
        method = st.selectbox("Method", list(brew_sheet_lib.METHODS))
    conn = models.connect(DB_PATH)
    try:
        sheet = brew_sheet_lib.build_brew_sheet(conn, lot_options[lot], method=method)
    finally:
        conn.close()
    html = brew_sheet_lib.render_brew_sheet_html(sheet)
    st.markdown(html, unsafe_allow_html=True)
    st.download_button(
        "Download brew sheet (HTML)",
        f"<!doctype html><meta charset='utf-8'><title>{sheet['lot_name']} brew sheet</title><body style='background:#F3F1ED;padding:24px'>{html}",
        file_name=f"brew_sheet_{sheet['lot_name'].replace(' ', '_').lower()}.html",
        mime="text/html",
    )


def data_library(s: dict, roasts: pd.DataFrame) -> None:
    st.title("Data library")
    st.markdown('<p class="lede">A single local record connecting green lots, roast curves, and cup scores.</p>', unsafe_allow_html=True)
    st.markdown('<div class="phase-lock"><strong>Demo workspace:</strong> the records below are deterministic synthetic data. Real imports stay disabled until GoodCup provides representative source files and confirms field mapping. This prevents a polished demo from quietly becoming an unverified production parser.</div>', unsafe_allow_html=True)
    st.write("")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.download_button("Download green intake template", (ROOT / "templates" / "green_intake.csv").read_bytes(), "green_intake.csv")
    with c2:
        st.download_button("Download roast template", (ROOT / "templates" / "roast_manual.csv").read_bytes(), "roast_manual.csv")
    with c3:
        st.download_button("Download cupping template", (ROOT / "templates" / "cupping_entry.csv").read_bytes(), "cupping_entry.csv")
    st.dataframe(roasts[["roast_ref", "roast_date", "lot_name", "origin_country", "process", "machine_id", "dtr_pct", "mean_total_score", "n_cuppings"]], width="stretch", hide_index=True, column_config={"dtr_pct": st.column_config.NumberColumn("DTR %", format="%.1f"), "mean_total_score": st.column_config.NumberColumn("Cup score", format="%.2f")})


inject_css()
ensure_demo()
mtime = DB_PATH.stat().st_mtime
s = summary_data(mtime)
roasts = roast_table(mtime)

with st.sidebar:
    st.image(str(ROOT / "assets" / "goodcup-mark.png"), width=76)
    st.markdown("<div style='text-align:center;font-size:.66rem;letter-spacing:.16em;font-weight:700;margin-top:-.7rem;margin-bottom:1.2rem'>ROAST INTELLIGENCE</div>", unsafe_allow_html=True)
    page = st.radio("Navigation", ["Overview", "Lot history", "Experiment Lab", "Roast insights", "Calibration", "Flavor & knowledge", "Brew sheet", "Data library"], label_visibility="collapsed", key="nav_page")
    st.divider()
    st.caption("LOCAL · OFFLINE · SQLITE")
    st.caption("Client demo · v0.1")

workspace_header()
if page == "Overview":
    overview(s, roasts, mtime)
elif page == "Lot history":
    lot_history_page(roasts, mtime)
elif page == "Experiment Lab":
    experiment_lab()
elif page == "Roast insights":
    roast_insights(roasts, mtime)
elif page == "Calibration":
    calibration_page(mtime)
elif page == "Flavor & knowledge":
    flavor_knowledge_page(roasts, mtime)
elif page == "Brew sheet":
    brew_sheet_page(roasts)
else:
    data_library(s, roasts)
