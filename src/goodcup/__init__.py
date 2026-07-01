"""GoodCup Roast-to-Cup Intelligence.

A local-first, single-user system that ingests green-coffee data, roast logs and
cupping scores, then answers -- *honestly* -- which roast variables are associated
with cup quality in our own data, surfaces cupper calibration drift, and (once
enough data exists) recommends a starting roast profile for a new green via
interpretable nearest-neighbours.

The durable value here is the data plus honest analysis, not model sophistication.
The statistical guardrails in ``analysis.correlation`` and the data-volume gate in
``recommend.similarity`` are the point of the tool, not decoration.
"""

__version__ = "0.1.0"
