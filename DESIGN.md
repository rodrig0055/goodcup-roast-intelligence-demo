# DESIGN.md: GoodCup Roast Intelligence

## Source

- URL: https://goodcup.ph
- Capture date: 2026-07-01
- Evidence: Firecrawl branding extraction, image inventory, and homepage screenshot in `.firecrawl/`

## Reference Screenshot

![GoodCup homepage](./.firecrawl/goodcup-screenshot.png)

## Design Summary

A light, precise product UI that carries GoodCup's warm neutral canvas, near-black typography, vivid green accent, and simple cup-mark identity into an R&D instrument.

## Design Tokens

### Colors

- Canvas: `oklch(0.965 0.008 85)`
- Surface: `oklch(0.985 0.004 85)`
- Ink: `oklch(0.16 0.008 85)`
- Muted ink: `oklch(0.48 0.01 85)`
- Rule: `oklch(0.87 0.008 85)`
- GoodCup green: `oklch(0.59 0.20 143)`
- Soft green: `oklch(0.94 0.035 143)`
- Review orange: `oklch(0.66 0.17 45)`

### Typography

Use Inter with system fallbacks. Headings are compact and bold; body and controls use a disciplined 13 to 15px scale. Data labels use tabular numerals.

### Spacing And Layout

Use an 8px base rhythm, a 220px desktop sidebar, 24 to 32px page gutters, 8px controls, thin rules, and restrained 8 to 12px radii. Prefer open rails, charts, and tables over nested cards.

## Components

Primary buttons are green, compact, and lightly rounded. Filters are white with thin borders. Selected navigation uses a soft green field and a narrow green indicator. Data panels use a single border and almost no shadow.

## Page Patterns

Persistent sidebar, quiet workspace header, strong task heading, KPI rail, then a two-column analysis-and-interpretation region followed by full-width curve or table views. Mobile collapses the sidebar and stacks analysis regions.

## Content Style

Plain, cautious, and operational. Use "associated with", always show N and uncertainty, and tell the roaster what could be tested next without implying causation.

## Agent Build Instructions

Keep true app text code-native. Use the green accent only for selection, action, and meaningful data emphasis. Never disguise synthetic data or unlock recommendation logic from demo volume alone.

## Rerun Inputs

workflow: firecrawl-website-design-clone
source_url: https://goodcup.ph
target_stack: Streamlit + Plotly
output: DESIGN.md
