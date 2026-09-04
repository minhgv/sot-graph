"""sot_graph.parser_outcome — Truthful classification of parser results.

Every built-in extraction/verification step must be able to say HOW its
evidence was produced. A symbol recovered purely from regex token coverage
is NOT equivalent to one recovered from a complete AST parse, and downstream
trust decisions (verifier confidence, ``confirmed`` flags, provider
metadata) key off this classification.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ParserOutcome(str, Enum):
    """How a parser/extraction step actually went.

    - PARSER_UNAVAILABLE: the grammar/parser backend is not installed or not
      configured for this language (nothing was even attempted).
    - PARSE_ERROR: the parser was available but raised while parsing.
    - VALID_EMPTY: the parse succeeded but yielded zero symbols/edges.
    - PARTIAL_AST: only the regex/heuristic fallback produced results.
    - COMPLETE: a full AST parse produced the results.
    """

    PARSER_UNAVAILABLE = "PARSER_UNAVAILABLE"
    PARSE_ERROR = "PARSE_ERROR"
    VALID_EMPTY = "VALID_EMPTY"
    PARTIAL_AST = "PARTIAL_AST"
    COMPLETE = "COMPLETE"


def package_version() -> str:
    """Version of the sot-graph package (used as extractor version stamp).

    The fallback import is deliberately inside the function: this module
    sits in the package's own import chain, so a module-level import of
    ``sot_graph.__version__`` would be circular.
    """
    try:
        import importlib.metadata

        return importlib.metadata.version("sot-graph")
    except Exception:
        from sot_graph import __version__

        return __version__


def coerce_outcome(value: Any) -> Optional[ParserOutcome]:
    """Tolerantly convert a stored/serialized value back to ParserOutcome."""
    if isinstance(value, ParserOutcome):
        return value
    if isinstance(value, str):
        try:
            return ParserOutcome(value)
        except ValueError:
            return None
    return None


def build_extractor_metadata(
    extractor_name: str,
    parser_outcome: Any,
    fallback_reason: Optional[str] = None,
    extractor_version: Optional[str] = None,
) -> Dict[str, Any]:
    """Provenance metadata attached to every built-in assertion.

    Shape matches the ``metadata_json`` column of provider_evidence so any
    writer can embed it verbatim without a schema change.
    """
    outcome = coerce_outcome(parser_outcome)
    return {
        "extractor": extractor_name,
        "extractor_version": extractor_version or package_version(),
        "parser_outcome": outcome.value if outcome else None,
        "fallback_reason": fallback_reason,
    }
