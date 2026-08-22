"""
sot_graph.verifier — Trust Verdict Engine.
Calculates lexical content coverage against physical disk files, validates file existence,
and performs deterministic rehoming or auto-purging of dead paths.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from sot_graph.db import Database

# Stop words ignored during lexical coverage calculation
STOP_WORDS: Set[str] = {
    "the", "and", "for", "with", "from", "that", "this", "have", "are", "was",
    "you", "your", "not", "but", "its", "all", "can", "has", "had", "she",
    "her", "him", "his", "our", "their", "them", "who", "whom", "which",
    "what", "when", "where", "why", "how", "into", "than", "then", "they",
    "self", "class", "def", "function", "return", "import", "const", "let", "var",
}

IGNORED_DIRS: Set[str] = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    "target", ".cache", ".idea", ".vscode", "coverage", ".next", ".turbo",
}


def tokenize(text: str) -> Set[str]:
    """Tokenizes text into normalized alphanumeric keywords >= 3 chars."""
    if not text:
        return set()
    tokens = re.findall(r"[a-zA-Z0-9_.\-/]{3,}", text.lower())
    return {t for t in tokens if t not in STOP_WORDS}


class TrustVerifier:
    @staticmethod
    def calculate_coverage(file_path: str, query_tokens: Set[str], max_bytes: int = 262144) -> Optional[float]:
        """
        Reads up to max_bytes (default 256KB) from physical file and computes
        the fraction of query tokens present in the actual disk content.
        Returns None if file cannot be read, is binary, or is oversized.
        """
        if not query_tokens or not os.path.exists(file_path):
            return None
        try:
            st = os.stat(file_path)
            if st.st_size > max_bytes:
                return None
            with open(file_path, "rb") as f:
                raw = f.read(max_bytes)
            if b"\x00" in raw[:1024]:  # Binary guard
                return None
            content = raw.decode("utf-8", errors="replace").lower()
            hit = sum(1 for t in query_tokens if t in content)
            return hit / len(query_tokens)
        except Exception:
            return None

    @staticmethod
    def find_rehome(project_root: str, basename: str) -> Optional[str]:
        """
        Scans project_root for a single unambiguous file with the given basename.
        Used to heal moved/renamed files automatically.
        """
        cands = []
        for root, dirs, files in os.walk(project_root):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            if basename in files:
                cands.append(os.path.abspath(os.path.join(root, basename)))
                if len(cands) > 1:
                    return None  # Ambiguous match, do not guess
        return cands[0] if len(cands) == 1 else None

    @classmethod
    def verify_hit(
        cls,
        db: Database,
        candidate: Dict[str, Any],
        query_tokens: Set[str],
        project_root: str,
        threshold: float = 0.5,
    ) -> Tuple[str, Optional[float], str]:
        """
        Verifies a search hit against disk reality:
        - STRONG: Path physically exists, coverage >= threshold (or no query tokens).
        - WEAK: Path physically exists, but coverage < threshold.
        - REBUILT: Path missing, but single file found elsewhere -> re-anchored.
        - REMOVED: Path missing and cannot be rehomed -> purged from DB.
        - NOPATH: Virtual node without an anchored disk file (e.g. manual note).
        """
        path = candidate.get("path")
        node_id = candidate["id"]

        if not path or not path.strip():
            return "NOPATH", 1.0, ""

        if os.path.exists(path) and os.path.isfile(path):
            cov = cls.calculate_coverage(path, query_tokens)
            if cov is not None:
                verdict = "STRONG" if cov >= threshold else "WEAK"
            else:
                verdict = "STRONG"
            return verdict, cov, path

        # File is missing on disk — check for rehoming
        basename = os.path.basename(path)
        new_path = cls.find_rehome(project_root, basename)
        if new_path and os.path.exists(new_path):
            db.update_node_path(node_id, path, new_path)
            cov = cls.calculate_coverage(new_path, query_tokens)
            return "REBUILT", cov, new_path

        # Dead path: Purge all nodes belonging to this dead path from database so it never ranks again
        db.delete_path(path)
        return "REMOVED", 0.0, path
