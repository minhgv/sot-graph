"""G9: truncated/corrupt SCIP protobuf must fail loudly with byte counts.

Before G9 the decoder silently ``break``-ed when a frame overran its
buffer, importing a partial graph with zero signal. Now every parse site
raises :class:`ScipTruncationError` carrying offset / remaining /
field_number counts.
"""
from __future__ import annotations

import pytest

from sot_graph.importer.scip import (
    ScipImporter,
    ScipTruncationError,
    parse_scip_protobuf,
)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _ld(field: int, payload: bytes) -> bytes:
    """Build a complete length-delimited frame."""
    return _tag(field, 2) + _varint(len(payload)) + payload


def test_intact_minimal_index_still_parses() -> None:
    """Always-strict decoding must not reject well-formed payloads."""
    doc_payload = _tag(4, 2) + _varint(4) + b"java"  # language field
    data = _ld(1, b"") + _ld(2, doc_payload)
    index = parse_scip_protobuf(data)
    assert len(index["documents"]) == 1
    assert index["documents"][0]["language"] == "java"


def test_truncated_top_level_frame_raises_with_counts() -> None:
    data = _ld(1, b"") + _tag(2, 2) + _varint(50) + b"\x00" * 10
    with pytest.raises(ScipTruncationError) as ei:
        parse_scip_protobuf(data)
    err = ei.value
    assert err.field_number == 2
    assert err.offset == len(data) - 10
    assert err.remaining == 10
    assert "50" in str(err) and "10" in str(err)


def test_truncated_nested_occurrence_raises_with_counts() -> None:
    # Document frame itself is consistent; the occurrence frame inside it
    # declares 9 bytes but only 4 are present.
    doc_payload = _tag(2, 2) + _varint(9) + b"\x00" * 4
    with pytest.raises(ScipTruncationError) as ei:
        parse_scip_protobuf(_ld(2, doc_payload))
    err = ei.value
    assert err.field_number == 2
    assert err.offset == 2
    assert err.remaining == 4
    assert "9" in str(err) and "4" in str(err)


def test_unsupported_wire_type_raises() -> None:
    data = (1 << 3) | 6  # wire type 6 does not exist in protobuf
    with pytest.raises(ScipTruncationError) as ei:
        parse_scip_protobuf(bytes([data]) + b"\x00" * 4)
    assert "unsupported wire type 6" in str(ei.value)
    assert ei.value.field_number == 1


def test_dangling_varint_raises_with_field_minus_one() -> None:
    # Length varint starts with a continuation byte and the buffer ends.
    with pytest.raises(ScipTruncationError) as ei:
        parse_scip_protobuf(b"\x0a\x80")
    err = ei.value
    assert err.field_number == 1
    assert err.remaining == 1
    assert "varint" in err.reason


def test_importer_parse_index_propagates_truncation() -> None:
    class _StubDB:
        project_root = "."

    truncated = _ld(1, b"") + _tag(2, 2) + _varint(50) + b"\x00" * 3
    with pytest.raises(ScipTruncationError):
        ScipImporter(_StubDB()).parse_index(truncated)
