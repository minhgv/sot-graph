"""Report generator: caller outside the indexed target directories.

This module lives at repo root (outside core/ and app/) and calls into
the target package, exercising cross-directory caller attribution.
"""
from core.service import compute_total


def run_report() -> float:
    # Ground truth: caller outside app/ and core/ -> compute_total
    return compute_total(9.99, 3)
