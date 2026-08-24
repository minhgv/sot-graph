"""
tests/property/test_invariants.py - Hypothesis Stateful Property-Based Invariant Tests for sot-graph.

Verifies:
1. Physical disk SHA matches journal SHA <=> node status is FRESH.
2. Context pack output token count <= max_tokens (with <= 5% allowance for indivisible single-line tokens).
3. Zero mixed snapshot generations in a single Context Pack.
4. User notes (kind == 'note') are NEVER dropped or corrupted across reconcile/clean cycles.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple

import hypothesis.strategies as st
from hypothesis import settings
from hypothesis.stateful import (
    RuleBasedStateMachine,
    invariant,
    rule,
)

from sot_graph.db import Database
from sot_graph.evidence import FreshnessStatus
from sot_graph.pack import PackError, build_bundle, render_yaml
from sot_graph.reconciler import Reconciler
from sot_graph.tokenizer import estimate_tokens
from sot_graph.verifier import TrustVerifier, tokenize


class SotGraphStateMachine(RuleBasedStateMachine):
    """
    Hypothesis RuleBasedStateMachine exploring arbitrary sequences of:
    - File creation, modification, deletion
    - User note insertion
    - Reconcile passes
    - Clean passes (stale/reset)
    - Context bundle packaging
    - Trust verification
    """

    def __init__(self) -> None:
        super().__init__()
        self.temp_dir = tempfile.mkdtemp(prefix="sot_prop_test_")
        self.db_path = os.path.join(self.temp_dir, ".sot", "sot.db")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, self.temp_dir)
        self.files: Dict[str, str] = {}  # rel_path -> content
        self.notes: Dict[str, Tuple[str, str, str]] = {}  # note_id -> (title, body, keywords)
        self.created_symbols: List[str] = []

    def teardown(self) -> None:
        try:
            self.db.close()
        except Exception:
            pass
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        super().teardown()

    # -------------------------------------------------------------------------
    # Rules
    # -------------------------------------------------------------------------

    @rule(
        filename=st.sampled_from(["mod_a.py", "mod_b.py", "service.py", "core.py", "utils.py"]),
        symbol_name=st.sampled_from(["alpha", "beta", "gamma", "delta", "epsilon", "processor"]),
        body_text=st.text(alphabet="abcdefghijklmnopqrstuvwxyz ", min_size=5, max_size=50),
    )
    def create_or_update_file(self, filename: str, symbol_name: str, body_text: str) -> None:
        rel_path = filename
        full_path = os.path.join(self.temp_dir, rel_path)
        
        # Build valid Python module code
        content = (
            f"# File: {filename}\n"
            f"def {symbol_name}(param: str) -> str:\n"
            f"    \"\"\"{body_text.strip()}\"\"\"\n"
            f"    return f'res_{symbol_name}:' + param\n\n"
            f"class {symbol_name.capitalize()}Handler:\n"
            f"    def handle(self) -> str:\n"
            f"        return {symbol_name}('data')\n"
        )
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.files[rel_path] = content
        if symbol_name not in self.created_symbols:
            self.created_symbols.append(symbol_name)

    @rule(
        filename=st.sampled_from(["mod_a.py", "mod_b.py", "service.py", "core.py", "utils.py"])
    )
    def mutate_file_content(self, filename: str) -> None:
        if filename not in self.files:
            return
        full_path = os.path.join(self.temp_dir, filename)
        if not os.path.exists(full_path):
            return
        
        # Append or modify content to introduce drift without syntax error
        content = self.files[filename] + f"\n# Mutated comment {os.urandom(4).hex()}\n"
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        self.files[filename] = content

    @rule(
        filename=st.sampled_from(["mod_a.py", "mod_b.py", "service.py", "core.py", "utils.py"])
    )
    def delete_file(self, filename: str) -> None:
        if filename in self.files:
            full_path = os.path.join(self.temp_dir, filename)
            if os.path.exists(full_path):
                os.remove(full_path)
            del self.files[filename]

    @rule(
        title=st.text(alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ", min_size=3, max_size=30),
        body=st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789 .,\n", min_size=5, max_size=60),
        keywords=st.text(alphabet="abcdefghijklmnopqrstuvwxyz,", min_size=3, max_size=20),
    )
    def insert_user_note(self, title: str, body: str, keywords: str) -> None:
        content = f"{title}\n{body}"
        note_id = f"note:{hashlib.sha256(content.encode()).hexdigest()[:12]}"
        with self.db.write_lock():
            with self.db.conn:
                self.db.conn.execute("""
                    INSERT INTO graph_nodes (id, path, kind, symbol, label, body, keywords, line_start, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        path=excluded.path, label=excluded.label, body=excluded.body,
                        keywords=excluded.keywords, updated_at=excluded.updated_at
                """, (
                    note_id, "", "note", None, title, body, keywords, 1, 1000
                ))
        self.notes[note_id] = (title, body, keywords)

    @rule()
    def reconcile_repo(self) -> None:
        self.reconciler.reconcile()

    @rule(reset=st.booleans())
    def clean_stale_data(self, reset: bool) -> None:
        # Default clean: never pass include_notes=True so notes must be preserved!
        plan = self.db.plan_clean(self.temp_dir, reset=reset, include_notes=False)
        self.db.apply_clean(plan)

    # -------------------------------------------------------------------------
    # Invariants
    # -------------------------------------------------------------------------

    @invariant()
    def invariant_1_freshness_reflects_physical_disk_sha(self) -> None:
        """
        Invariant 1: Physical disk SHA matches journal SHA <=> node status is FRESH.
        """
        journals = self.db.get_all_file_journals()
        for rel_path, expected_content in self.files.items():
            full_path = os.path.join(self.temp_dir, rel_path)
            if not os.path.exists(full_path):
                continue
            with open(full_path, "rb") as f:
                disk_sha = hashlib.sha256(f.read()).hexdigest()
            
            norm_rel = rel_path.replace(os.sep, "/")
            journal_entry = journals.get(norm_rel) or journals.get(full_path)
            
            # Check candidate node for this file
            node_row = self.db.conn.execute(
                "SELECT id, path, kind, symbol, fqn, line_start FROM graph_nodes WHERE (path = ? OR path = ?) AND kind NOT IN ('file', 'note') LIMIT 1",
                (norm_rel, full_path)
            ).fetchone()
            
            if node_row and journal_entry:
                cand = {
                    "id": node_row[0],
                    "path": node_row[1],
                    "kind": node_row[2],
                    "symbol": node_row[3],
                    "fqn": node_row[4],
                    "line_start": node_row[5],
                }
                res = TrustVerifier.verify_hit(
                    self.db, cand, tokenize(cand["symbol"] or "sym"), self.temp_dir,
                    threshold=0.0, auto_heal=False, jit_reconcile=False
                )
                evidence = res.evidence
                
                journal_sha = journal_entry["sha256"]
                if disk_sha == journal_sha:
                    assert evidence.freshness == FreshnessStatus.FRESH, (
                        f"Expected FRESH for {rel_path} with matching SHA {disk_sha}, got {evidence.freshness}"
                    )
                else:
                    assert evidence.freshness in (FreshnessStatus.STALE, FreshnessStatus.UNKNOWN), (
                        f"Expected STALE/UNKNOWN for drifted file {rel_path}, got {evidence.freshness}"
                    )

    @invariant()
    def invariant_2_context_pack_token_budget_bound(self) -> None:
        """
        Invariant 2: Context pack output token count <= max_tokens (with <= 5% allowance for indivisible single-line tokens).
        """
        # Pick an indexed symbol if available
        row = self.db.conn.execute(
            "SELECT symbol FROM graph_nodes WHERE kind NOT IN ('file', 'note') AND symbol IS NOT NULL AND symbol != '' LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return
        target_symbol = row[0]
        for max_tokens in [500, 1000, 2000]:
            try:
                bundle = build_bundle(
                    self.db,
                    self.temp_dir,
                    target_symbol,
                    max_tokens=max_tokens,
                )
                rendered = render_yaml(bundle)
                actual_tokens = estimate_tokens(rendered)
                # Pack guarantees actual_tokens <= max_tokens
                assert actual_tokens <= max_tokens, (
                    f"Bundle exceeded budget: actual {actual_tokens} > target {max_tokens}"
                )
            except PackError:
                # Expected fail-closed packaging behavior for drifted/ambiguous/small-budget targets
                continue

    @invariant()
    def invariant_3_zero_mixed_snapshot_generations(self) -> None:
        """
        Invariant 3: Zero mixed snapshot generations in a single Context Pack.
        All referenced nodes in a context pack must come from consistent file journal records.
        """
        row = self.db.conn.execute(
            "SELECT symbol FROM graph_nodes WHERE kind NOT IN ('file', 'note') AND symbol IS NOT NULL AND symbol != '' LIMIT 1"
        ).fetchone()
        if not row or not row[0]:
            return
        target_symbol = row[0]
        try:
            bundle = build_bundle(self.db, self.temp_dir, target_symbol)
        except PackError:
            # Expected fail-closed packaging behavior for drifted/ambiguous/small-budget targets
            return

        target_info = bundle.get("target", {})
        target_sha = target_info.get("indexed_sha256")
        target_path = target_info.get("relative_path")
        target_gen = bundle.get("base_generation")
        if target_path and target_sha:
            j_entry = self.db.get_file_journal(target_path)
            if j_entry:
                assert j_entry["sha256"] == target_sha, (
                    f"Mixed snapshot generation detected! Pack target SHA {target_sha} != Journal SHA {j_entry['sha256']}"
                )
                if target_gen is not None:
                    assert j_entry["generation"] == target_gen, (
                        f"Target generation mismatch: journal {j_entry['generation']} != bundle {target_gen}"
                    )

        for caller in bundle.get("inbound_callers", []):
            c_node_id = caller.get("node_id")
            c_path = caller.get("relative_path")
            if c_node_id:
                node_row = self.db.conn.execute(
                    "SELECT path FROM graph_nodes WHERE id = ?", (c_node_id,)
                ).fetchone()
                if node_row and node_row[0]:
                    c_path = node_row[0]
            if c_path:
                j = self.db.get_file_journal(c_path)
                assert j is not None, f"Missing file journal for caller {c_node_id or c_path}"
                assert j.get("generation") is not None and j["generation"] >= 1, (
                    f"Invalid generation in caller {c_node_id or c_path}: {j.get('generation')}"
                )
                assert j.get("sha256"), f"Missing sha256 in journal for caller {c_node_id or c_path}"

        for callee in bundle.get("outbound_callees", []):
            c_node_id = callee.get("node_id")
            c_path = callee.get("relative_path")
            if c_node_id:
                node_row = self.db.conn.execute(
                    "SELECT path FROM graph_nodes WHERE id = ?", (c_node_id,)
                ).fetchone()
                if node_row and node_row[0]:
                    c_path = node_row[0]
            if c_path:
                j = self.db.get_file_journal(c_path)
                assert j is not None, f"Missing file journal for callee {c_node_id or c_path}"
                assert j.get("generation") is not None and j["generation"] >= 1, (
                    f"Invalid generation in callee {c_node_id or c_path}: {j.get('generation')}"
                )
                assert j.get("sha256"), f"Missing sha256 in journal for callee {c_node_id or c_path}"
    @invariant()
    def invariant_4_user_notes_preserved(self) -> None:
        """
        Invariant 4: User notes (kind == 'note') are NEVER dropped or corrupted across reconcile/clean cycles.
        """
        for note_id, (expected_title, expected_body, expected_keywords) in self.notes.items():
            row = self.db.conn.execute(
                "SELECT id, label, body, keywords, kind FROM graph_nodes WHERE id = ?",
                (note_id,)
            ).fetchone()
            assert row is not None, f"User note {note_id} was dropped!"
            assert row[1] == expected_title, f"Note title corrupted: {row[1]} != {expected_title}"
            assert row[2] == expected_body, f"Note body corrupted: {row[2]} != {expected_body}"
            assert row[3] == expected_keywords, f"Note keywords corrupted: {row[3]} != {expected_keywords}"
            assert row[4] == "note", f"Note kind corrupted: {row[4]} != 'note'"


TestSotGraphInvariants = SotGraphStateMachine.TestCase
TestSotGraphInvariants.settings = settings(
    max_examples=25,
    stateful_step_count=15,
    deadline=None,
)
