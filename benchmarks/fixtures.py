"""Deterministic source fixtures and correctness helpers for benchmarks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
from typing import Any, Iterable


@dataclass(frozen=True)
class FixtureSpec:
    """Inputs that fully determine a generated fixture tree."""

    files: int = 5000
    seed: int = 20250219


def _source_for(language: str, index: int, seed: int) -> str:
    """Return a small valid source document with deterministic symbols."""
    token = f"fixture_{seed}_{index}"
    previous = f"fixture_{seed}_{index - 1}" if index else "fixture_{seed}_0"
    if language == "python":
        return (
            f"def {token}(value: int = {index}):\n"
            f"    return value + {index}\n\n"
            f"{token}_reference = {previous}\n"
        )
    if language == "typescript":
        return (
            f"export function {token}(value: number = {index}): number {{\n"
            f"  return value + {index};\n"
            f"}}\n\nexport const {token}_reference = \"{previous}\";\n"
        )
    if language == "go":
        return (
            "package fixture\n\n"
            f"func {token}(value int) int {{\n"
            f"\treturn value + {index}\n"
            "}\n"
        )
    if language == "rust":
        return (
            f"pub fn {token}(value: i64) -> i64 {{\n"
            f"    value + {index}\n"
            "}\n"
        )
    return (
        f"# Fixture {index}\n\n"
        f"- symbol: `{token}`\n"
        f"- previous: `{previous}`\n"
    )


def generate_fixture(root: Path | str, files: int = 5000, seed: int = 20250219) -> tuple[Path, ...]:
    """Create *files* deterministic files below *root* and return sorted paths."""
    if files < 1:
        raise ValueError("files must be positive")
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    languages = (
        ("python", ".py"),
        ("typescript", ".ts"),
        ("go", ".go"),
        ("rust", ".rs"),
        ("markdown", ".md"),
    )
    result: list[Path] = []
    for index in range(files):
        language, suffix = languages[index % len(languages)]
        relative = Path("fixtures") / language / f"file_{index:06d}{suffix}"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_source_for(language, index, seed), encoding="utf-8")
        result.append(relative)
    return tuple(result)


def mutate_fixture(root: Path | str, index: int, seed: int = 20250219) -> Path:
    """Change one generated file while retaining its language and path."""
    root = Path(root)
    languages = (("python", ".py"), ("typescript", ".ts"), ("go", ".go"), ("rust", ".rs"), ("markdown", ".md"))
    language, suffix = languages[index % len(languages)]
    path = root / "fixtures" / language / f"file_{index:06d}{suffix}"
    path.write_text(_source_for(language, index, seed) + f"\n# mutation {index}\n", encoding="utf-8")
    return path.relative_to(root)


def environment_fingerprint(**config: Any) -> dict[str, Any]:
    """Return reproducibility metadata without making performance claims."""
    result: dict[str, Any] = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "sqlite": sqlite3.sqlite_version,
        "python_executable": sys.executable,
    }
    result.update(config)
    return result


def _connection(db: Any) -> Any:
    connection = getattr(db, "_conn", None)
    if connection is None:
        connection = getattr(db, "conn", None)
    if connection is None:
        raise AttributeError("Database does not expose its connection")
    return connection


def canonical_snapshot(db: Any) -> dict[str, Any]:
    """Capture stable graph content, excluding timestamps and SQLite internals."""
    connection = _connection(db)
    tables = {
        "file_journal": ("path", "sha256", "size", "mtime_ms"),
        "graph_nodes": ("id", "path", "kind", "name", "line", "col", "signature", "content"),
        "graph_edges": ("src_id", "dst_id", "kind", "line"),
        "pending_edges": ("src_path", "src_name", "kind", "dst_path", "line"),
    }
    snapshot: dict[str, Any] = {}
    for table, columns in tables.items():
        available = [row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()]
        selected = [column for column in columns if column in available]
        if not selected:
            snapshot[table] = []
            continue
        sql = f"SELECT {', '.join(selected)} FROM {table} ORDER BY {', '.join(selected)}"
        snapshot[table] = [list(row) for row in connection.execute(sql).fetchall()]
    return snapshot


def canonical_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def correctness_projection(db: Any, queries: Iterable[str]) -> dict[str, Any]:
    """Project public query behavior used by worker-count correctness gates."""
    projection: dict[str, Any] = {"snapshot_hash": canonical_hash(canonical_snapshot(db))}
    projection["stats"] = db.stats()
    projection["search"] = {query: db.search_fts(query, limit=10) for query in queries}
    return projection


def jsonable(value: Any) -> Any:
    """Convert dataclasses and tuples for stable benchmark JSON."""
    if hasattr(value, "__dataclass_fields__"):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]
    return value
