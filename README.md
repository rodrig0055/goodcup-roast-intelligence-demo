# GoodCup Roast Intelligence

A local-first MVP for showing how GoodCup's green, roast, and cupping records can become an honest operational memory.

## Run the client demo

```bash
cd /Users/yiber/Documents/goodcup
source .venv/bin/activate
pip install -e .
goodcup demo
```

The app opens at `http://localhost:8501`. On first run it creates a deterministic synthetic workspace with 80 matched roasts and 240 cuppings. Every demo view is labeled. Synthetic volume does not authorize production recommendations.

The interactive Experiment Lab is intentionally session-only in the MVP. It demonstrates controlled-profile design, blind scoring, identity reveal, and a cautious confirmation-roast decision without pretending the prototype is a validated electronic lab notebook.

The Lot History page closes the roast-learning loop for each green: score trend across repeated roasts, BT/ET/RoR overlays for up to five profiles, best-roast parameter comparison, ambient-condition exploration, curve coverage, and repeatability spread. Curve overlays refuse mixed or missing temperature units instead of silently corrupting comparisons.

## Deploy to Streamlit Community Cloud

The app is deploy-ready — no secrets or API keys are needed (the AI layer runs an
offline mock by default). At [share.streamlit.io](https://share.streamlit.io):

- **Repository:** this GitHub repo · **Branch:** `main`
- **Main file path:** `src/goodcup/dashboard/app.py`
- **Python version** (Advanced settings): 3.12 (the repo requires ≥ 3.11)

Dependencies install from `requirements.txt`; `app.py` bootstraps its own import
path, so no editable install is needed. On first boot the app seeds the
deterministic synthetic workspace. Notes for the hosted demo:

- The app is **public** by link — this is fine because all data is synthetic and labeled.
- The container filesystem is **ephemeral**: the SQLite store re-seeds on reboot, so
  viewer-created state (recorded experiment decisions, cached literature) does not persist.
- It is a **single shared instance**, not multi-tenant.

If a deploy shows a stale error after a push, use **Manage app → Reboot** to pull
the latest commit.

## Verify

```bash
pytest -q
```

## Real-data gate

The included Artisan and Cropster fixtures are synthetic parser-development examples. Before production use, validate each parser against real GoodCup exports and keep those real files private. Phase 2 recommendations remain out of scope until the PRD's real-data gate is met.
