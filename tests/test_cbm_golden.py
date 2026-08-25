"""Golden wire-contract tests for the Codebase Memory CLI provider.

Every fixture in ``tests/fixtures/cbm_golden/`` is a verbatim stdout capture of
the real ``codebase-memory-mcp`` binary 0.10.8 against
``tests/fixtures/cbm_sample_repo/`` (see ``_meta.json`` for capture receipts).
These tests re-parse the captured envelopes and assert the mandatory schema
fields survive parsing.

NOTE(P2): this module intentionally carries its own minimal parser so the
golden suite does not depend on Worker B's
``src/sot_graph/providers/normalization.py`` while that lands. P2 will swap
this parser for the shared normalizer and delete the duplicated logic here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "cbm_golden"

# Tool -> required schema surface. For tools whose `content[0].text` is a JSON
# payload we require object keys; for text-report tools we require the report's
# header markers (the real wire format mixes both styles).
JSON_FIELDS: dict[str, set[str]] = {
    "index_status": {"project", "nodes", "edges", "status", "root_path"},
    "list_projects": {"projects", "total", "returned", "has_more"},
    "check_index_coverage": {"project", "signal", "indexed_at", "paths", "caveat"},
}

TEXT_MARKERS: dict[str, tuple[str, ...]] = {
    "search_graph": ("total:", "search_mode:", "results:", "has_more:"),
    "trace_path": ("function:", "direction:", "callees_total:"),
    "get_architecture": ("total_nodes:", "total_edges:", "node_labels:", "edge_types:"),
    "detect_changes": ("base:", "merge_base:", "direction:", "changed_files:"),
}

ALL_TOOLS = sorted(JSON_FIELDS) + sorted(TEXT_MARKERS)


def _load_raw(tool: str) -> str:
    path = GOLDEN_DIR / f"{tool}.json"
    assert path.is_file(), f"missing golden capture for {tool}: {path}"
    return path.read_text(encoding="utf-8")


def _load_envelope(tool: str) -> dict[str, Any]:
    """Minimal MCP-envelope validation: exactly what the adapter will rely on."""
    env = json.loads(_load_raw(tool))
    assert isinstance(env, dict), f"{tool}: envelope is not an object"
    assert env.get("isError") is False, f"{tool}: golden captured isError=true"
    content = env.get("content")
    assert isinstance(content, list) and content, f"{tool}: empty content array"
    first = content[0]
    assert first.get("type") == "text", f"{tool}: content[0].type != 'text'"
    text = first.get("text")
    assert isinstance(text, str) and text.strip(), f"{tool}: content[0].text empty"
    return env


def _parse_payload(tool: str, text: str) -> dict[str, Any] | str:
    """Parse content[0].text; JSON payload -> dict, otherwise text report."""
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
        assert isinstance(payload, dict)
        return payload
    return stripped


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_golden_envelope_schema(tool: str) -> None:
    """Envelope shape holds for every golden capture."""
    env = _load_envelope(tool)
    # structuredContent must be present iff the text payload itself is JSON.
    payload_is_json = env["content"][0]["text"].strip().startswith("{")
    has_sc = "structuredContent" in env
    assert has_sc == payload_is_json, (
        f"{tool}: structuredContent presence ({has_sc}) disagrees with "
        f"payload style (json={payload_is_json})"
    )


@pytest.mark.parametrize("tool", sorted(JSON_FIELDS))
def test_golden_json_fields(tool: str) -> None:
    """Required top-level fields exist in every JSON-payload golden."""
    env = _load_envelope(tool)
    payload = _parse_payload(tool, env["content"][0]["text"])
    assert isinstance(payload, dict), f"{tool}: expected JSON payload"
    missing = JSON_FIELDS[tool] - payload.keys()
    assert not missing, f"{tool}: missing required fields {sorted(missing)}"


@pytest.mark.parametrize("tool", sorted(TEXT_MARKERS))
def test_golden_text_report_markers(tool: str) -> None:
    """Required header markers exist in every text-report golden."""
    env = _load_envelope(tool)
    payload = _parse_payload(tool, env["content"][0]["text"])
    assert isinstance(payload, str), f"{tool}: expected text-report payload"
    for marker in TEXT_MARKERS[tool]:
        assert marker in payload, f"{tool}: missing report marker {marker!r}"


def test_search_graph_ground_truth_direct_call() -> None:
    """Ground truth: query 'compute_total' finds the definition in core/service.py."""
    env = _load_envelope("search_graph")
    payload = env["content"][0]["text"]
    assert "core/service.py" in payload
    assert "compute_total" in payload


def test_trace_path_ground_truth_callees() -> None:
    """Ground truth: build_invoice directly calls compute_total and format_label."""
    env = _load_envelope("trace_path")
    payload = env["content"][0]["text"]
    assert "callees_total: 2" in payload
    assert "compute_total 1" in payload
    assert "format_label 1" in payload


def test_meta_consistency() -> None:
    """_meta.json lists a capture receipt for every golden file present."""
    meta_path = GOLDEN_DIR / "_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["binary"]["version"] == "codebase-memory-mcp 0.10.8"
    receipts = {c["file"] for c in meta["captures"]}
    on_disk = {p.name for p in GOLDEN_DIR.glob("*.json")} - {"_meta.json"}
    assert receipts == on_disk, f"receipt/file mismatch: {receipts ^ on_disk}"
