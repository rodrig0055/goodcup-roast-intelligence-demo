# GoodCup working rules

- Implement in phases. Real ingestion must be verified before expanding production analysis.
- Never invent parser formats. Real `.alog`, Cropster, and cupping exports are ground truth.
- Always show N, 95% confidence intervals, effect sizes, raw p-values, and FDR-adjusted p-values.
- Use correlational language only. Flag mixed machines, origins, and processes as confounders.
- Recommendation stays disabled until at least 50 real matched roasts and 6 similar historical greens exist.
- Synthetic demo data must remain clearly labeled and must never be mixed with client data.
- SQLite is the production store. Keep dependencies small and local-first.
- Roast-metric tests are load-bearing. Run `pytest` before handoff.
