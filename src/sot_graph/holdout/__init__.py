"""SG-204 holdout benchmark package.

``evaluator`` is the independent (stdlib-only) oracle; the orchestration
lives in ``scripts/bench_holdout.py`` so the benchmark runner can import
sot_graph WITHOUT dragging extractor internals into the oracle module.
"""

__all__ = ["evaluator"]
