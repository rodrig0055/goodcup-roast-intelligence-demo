# How the industry digitizes roasting & cupping — and where GoodCup fits

*Captured 2026-07-01. Sources at the end. This is a strategy brief, not product
copy; it explains why GoodCup builds the layer it does.*

## The landscape

Coffee roasters already generate a lot of data — roast curves, cupping scores,
green analyses, costs, sales. The tools that capture it are mature and mostly
good at what they do. The problem is not capture; it is that the pieces live in
separate systems and the roast→cup relationship is described rather than
analyzed.

| Tool | What it does well | Model | Gap it leaves |
|------|-------------------|-------|---------------|
| **Cropster** (Roasting Intelligence / Green / Cup) | Real-time roast profiling, machine integration over Modbus/PLC, green inventory + lot traceability, cupping that now carries the SCA **CVA** descriptive form | Cloud SaaS, enterprise-priced | Links roast↔cup operationally but presents the relationship as reporting, with little effect-size / multiple-comparison / confounder discipline |
| **Artisan** | Best-in-class open-source curve logging (`.alog`), broad hardware support, precise profile analysis | Local desktop, free | No cupping linkage, no statistical analytics, no cloud memory |
| **RoasTime / RoastWorld** (Aillio Bullet) | Curve logging plus a cloud community that overlays other roasters' profiles on the same bean, with cupping notes | Cloud + community | "All-or-nothing" privacy and data-ownership complaints; centered on one machine |
| **Tastify / CatadorCVA / Cropster Cup** | Digital cupping; Tastify and CatadorCVA are official SCA **CVA** digital platforms | Cloud / app | Cupping only — not tied to *your* roast curves and greens |
| **RoastLog / RoastPATH / RoasteryPro** | Cloud roast logbooks, production and inventory management | Cloud SaaS | Operational, not analytical |
| **Academic ML** (FT-NIR + sensory; roast-level CNNs) | Predicts cup quality (~81% in one study) and roast level from spectra/images | Research | Requires spectroscopy/imaging hardware; not productized for a working roastery |

### The confirmed pain point

Across buyer guides, QC write-ups, and roaster community threads the same
picture recurs: **roast curves sit in Artisan, cupping scores in notebooks or a
cupping app, costs in Excel, and sales in a POS.** When a customer asks what a
lot scored, or a roaster asks whether last month's profile change actually
helped, the answer means stitching systems together by hand. Even Cropster,
which does link roast and cup, largely *reports* the pairing — it does not lead
with "here is the effect size, its 95% confidence interval, N, and the
FDR-adjusted p-value; treat it as a hypothesis to test."

## Where GoodCup fits

GoodCup is deliberately **not another roast logger.** It is the analysis and
institutional-memory layer that sits on top of logs a roastery already keeps:

- **Local-first and honesty-first.** One SQLite store links green → roast →
  curve → cupping. Every association is reported with N, a 95% CI, effect size,
  raw and FDR-adjusted p-values, and confounder flags, in strictly correlational
  language. That statistical discipline — not more logging — is the moat.
- **Complements rather than replaces.** It is designed to consume the outputs of
  Artisan / Cropster / CVA cupping, not to compete with their capture. (Real-file
  ingestion is intentionally deferred until representative client files exist;
  inventing parser formats would undermine the trust the product is built on.)
- **Remembers.** Cupper calibration, lot repeatability, experiment decisions, and
  the published science behind a hypothesis all become durable, queryable memory
  — the thing that otherwise walks out the door with the head roaster.

## The gap → three bets

Turning existing logs and knowledge into leverage, in priority order:

1. **Institutional knowledge layer.** Map free-text tasting notes onto the 2016
   WCR/SCA flavor wheel; persist experiment hypotheses, blind results, and
   decisions as durable records; and pull the **published science** behind each
   hypothesis into a reference library that is cited alongside the roastery's own
   evidence.
2. **Predictive / recommendation (gated).** Similar-green and roast-profile
   recommendations, plus an honest, interpretable roast→score predictor — both
   held behind the Phase-2 data gate (≥50 matched roasts, ≥6 similar greens) and
   never fabricated below it.
3. **Deeper analytics / QC.** Confounder-adjusted associations, SPC/drift
   monitoring of cupping consensus and roast stability, and sample-size guidance
   so experiments are powered to answer the question they pose.

### Literature integration

Published coffee science should inform the research process, not sit outside it.
GoodCup queries free scholarly APIs (Crossref, Semantic Scholar, arXiv — no API
key) for a hypothesis such as "development time ratio and cup score," and caches
the relevant papers into the local store, linked to the experiment they support.
The online pull is the single, clearly-separated network touchpoint; once cached,
references are available offline and cited in decision records. This keeps
external evidence and the roastery's own evidence side by side — the roaster sees
both what the literature found and what *their* data shows, with the same
insistence on effect sizes and uncertainty.

## Non-goals

- Not a roast logger or a machine-control system.
- Not cloud or multi-tenant — single-roastery, offline, local-first.
- Not a CVA data-entry app.
- Not a general literature database — only papers pulled for a specific
  hypothesis are cached.

## Sources

- Digital Coffee Future — profiling software and cupping apps:
  <https://www.digitalcoffeefuture.com/magazineen/three-profiling-software-systems-to-manage-roasting-data>,
  <https://www.digitalcoffeefuture.com/magazineen/five-apps-to-take-your-coffee-cupping-activities-to-the-digital-world>
- Cropster — machine integration and QC:
  <https://help.cropster.com/connecting-your-roast-machine>,
  <https://www.cropster.com/blog-post/managing-quality-assurance-and-quality-control/>
- SCA — Coffee Value Assessment on digital platforms:
  <https://sca.coffee/sca-news/the-coffee-value-assessment-and-tools-expands-to-two-digital-platforms>
- Tastify: <https://www.tastify.com/> · Cropster Cup:
  <https://www.cropster.com/blog-post/cropsters-new-cupping-app-explaining-cropster-cup/>
- RoastWorld / Aillio community and data ownership: <https://roast.world/>,
  <https://community.roast.world/t/private-roast-data-in-roast-world/9850>
- QC workflow fragmentation:
  <https://perfectdailygrind.com/2022/01/streamlining-quality-control-in-your-coffee-roastery/>
- ML for cup-quality prediction (research):
  <https://link.springer.com/chapter/10.1007/978-3-030-61834-6_5>; FT-NIR + sensory
  dataset: <https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12142347/>
