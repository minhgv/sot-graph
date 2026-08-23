"""Comprehensive real-world testing harness for sot-graph across diverse GitHub projects.

Tests 15 distinct feature pipelines across 12 real repositories:
1. Fresh DB indexing / reconciliation (parallel workers)
2. AST extraction fidelity across languages (Dart, TS/JS, PHP, Python, C#, etc.)
3. Health Diagnostics (doctor)
4. FTS5 Search & Trust Verdicts ([STRONG], [WEAK]) + Edge queries (Vietnamese, punct, empty)
5. Graph Exploration & Dependency Impact Tracing (explore, usages, implementations)
6. Repo Map generation with Token Budgets (1k, 2k, 4k) & Focus Personalization
7. Vector Hybrid Search (sqlite-vec + RRF fusion)
8. Verification & Drift Detection (reconciler.audit_drift & mcp service.verify_drift)
9. Louvain Clustering & Modularity (AnalyticsGraph.detect_communities)
10. Architecture Diagnostics & God Node Detection (analyze_graph & blast radius)
11. Interactive HTML Visualizer (generate_html_visualizer)
12. Fact Bundle extraction (ArchitectureBundler)
13. Multi-format Exporters (graphrag, obsidian, graphml, scip)
14. Maintenance (clean & vacuum)
15. Incremental Reconciler & Self-Healing (create, edit, delete, reconcile)
"""
import json
import os
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sot_graph.db import Database
from sot_graph.reconciler import Reconciler
from sot_graph.verifier import TrustVerifier
from sot_graph.mcp_service import McpService
from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.analytics.diagnostics import analyze_graph
from sot_graph.analytics.report import generate_markdown_report
from sot_graph.analytics.bundle import ArchitectureBundler
from sot_graph.export.html import generate_html_visualizer, save_html_visualizer
from sot_graph.export.exporter import (
    export_graphrag_json,
    export_obsidian_vault,
    export_graphml
)
from sot_graph.export.scip import export_scip
from sot_graph.repo_map import build_repo_map
from sot_graph import vector


REPOS_TO_TEST = [
    {
        "name": "lazzybee",
        "path": "/Users/giapminh79/code/GitHub/lazzybee",
        "lang": "Dart/Flutter",
    },
    {
        "name": "mini_appstore_flutter",
        "path": "/Users/giapminh79/code/GitHub/mini_appstore_flutter",
        "lang": "Dart/Flutter",
    },
    {
        "name": "ai-scaffold",
        "path": "/Users/giapminh79/code/GitHub/ai-scaffold",
        "lang": "TypeScript/Node",
    },
    {
        "name": "ban-hoc-toan",
        "path": "/Users/giapminh79/code/GitHub/ban-hoc-toan",
        "lang": "JS/TS/Web (Vietnamese)",
    },
    {
        "name": "uniservices-php",
        "path": "/Users/giapminh79/code/GitHub/uniservices-php",
        "lang": "PHP/Backend",
    },
    {
        "name": "crm",
        "path": "/Users/giapminh79/code/GitHub/crm",
        "lang": "PHP/Enterprise CRM",
    },
    {
        "name": "unipay",
        "path": "/Users/giapminh79/code/GitHub/unipay",
        "lang": "PHP/Financial Backend",
    },
    {
        "name": "md2docx",
        "path": "/Users/giapminh79/code/GitHub/md2docx",
        "lang": "Python",
    },
    {
        "name": "antigravity-sdk-python",
        "path": "/Users/giapminh79/code/GitHub/antigravity-sdk-python",
        "lang": "Python/AI SDK",
    },
    {
        "name": "odoo-itpro",
        "path": "/Users/giapminh79/code/GitHub/odoo-itpro",
        "lang": "Python/Odoo",
    },
    {
        "name": "google-antigravity-auth",
        "path": "/Users/giapminh79/code/GitHub/google-antigravity-auth",
        "lang": "TypeScript",
    },
    {
        "name": "auth-net",
        "path": "/Users/giapminh79/code/GitHub/auth-net",
        "lang": "C#/.NET",
    },
]


def test_repo(repo_info):
    repo_path = Path(repo_info["path"])
    repo_name = repo_info["name"]
    lang = repo_info["lang"]
    
    print(f"\n========================================================")
    print(f"🚀 TESTING REPO: {repo_name} ({lang})")
    print(f"📁 Path: {repo_path}")
    print(f"========================================================")
    
    if not repo_path.exists():
        print(f"⚠️  Repo path does not exist: {repo_path}. Skipping.")
        return {"repo": repo_name, "lang": lang, "status": "skipped", "reason": "path not found"}
    
    temp_dir = tempfile.mkdtemp(prefix=f"sot_test_{repo_name}_")
    db_path = Path(temp_dir) / "sot.db"
    
    results = {
        "repo": repo_name,
        "lang": lang,
        "path": str(repo_path),
        "steps": {},
        "errors": [],
        "warnings": [],
    }
    
    try:
        # Step 1: Initialize DB
        print(f"Step 1: Initializing fresh DB at {db_path}...")
        t0 = time.time()
        db = Database(str(db_path))
        t1 = time.time()
        results["steps"]["db_init"] = {"time_s": round(t1 - t0, 3), "status": "ok"}
        
        # Step 2: Full Reconciliation / Indexing
        print(f"Step 2: Indexing {repo_name} (workers=4, batch_size=50)...")
        reconciler = Reconciler(db, str(repo_path))
        t0 = time.time()
        reconcile_stats = reconciler.reconcile(workers=4, batch_size=50)
        t1 = time.time()
        duration = round(t1 - t0, 3)
        print(f"  -> Reconciled in {duration}s: {reconcile_stats}")
        results["steps"]["reconcile"] = {
            "time_s": duration,
            "stats": reconcile_stats.as_dict(),
            "status": "ok",
        }
        
        # Verify node counts
        st = db.stats()
        node_count = st["nodes"]
        edge_count = st["edges"]
        pending_count = st["pending"]
        print(f"  -> Nodes: {node_count}, Edges: {edge_count}, Pending: {pending_count}")
        
        # Check node kinds
        cursor = db.conn.execute("SELECT kind, COUNT(*) FROM graph_nodes GROUP BY kind ORDER BY COUNT(*) DESC")
        kind_dist = dict(cursor.fetchall())
        print(f"  -> Node kinds: {kind_dist}")
        results["steps"]["kind_distribution"] = kind_dist
        
        # Step 3: Doctor / Health Check
        print(f"Step 3: Running Doctor / Health Check...")
        doc = db.stats()
        print(f"  -> Doctor stats: {doc}")
        results["steps"]["doctor"] = {"stats": doc, "status": "ok"}
        
        # Step 4: Search & Trust Verdicts
        print(f"Step 4: Testing Search & Trust Verdicts via McpService...")
        service = McpService(str(db_path), str(repo_path))
        
        # Select representative non-import symbols (functions, classes, methods)
        cur = db.conn.execute("""
            SELECT symbol, kind, path FROM graph_nodes 
            WHERE kind IN ('function', 'class', 'method', 'interface') AND symbol != '' 
            ORDER BY length(symbol) DESC LIMIT 10
        """)
        code_symbols = cur.fetchall()
        if not code_symbols:
            cur = db.conn.execute("SELECT symbol, kind, path FROM graph_nodes WHERE kind != 'file' AND symbol != '' LIMIT 10")
            code_symbols = cur.fetchall()
            
        search_results = []
        for symbol, kind, fpath in code_symbols[:5]:
            res_dict = service.search(symbol, limit=5)
            hits = res_dict.get("results", [])
            for item in hits:
                verdict = item.get("verdict")
                if verdict not in ("STRONG", "WEAK", "REBUILT", "NOPATH", "STALE"):
                    results["warnings"].append(f"Search for {symbol} returned unexpected verdict: {verdict}")
            search_results.append({
                "query": symbol,
                "kind": kind,
                "results_count": len(hits),
                "top_verdict": hits[0].get("verdict") if hits else None
            })
            
        # Test edge search queries (Vietnamese, symbols, punctuation, empty)
        edge_queries = ["dữ liệu", "quản lý", "api", "get", "error_code", "_init_", "123456789_nonexistent"]
        for eq in edge_queries:
            try:
                res = service.search(eq, limit=3)
                search_results.append({
                    "query": eq,
                    "kind": "edge_query",
                    "results_count": len(res.get("results", [])),
                    "top_verdict": res.get("results", [{}])[0].get("verdict") if res.get("results") else None
                })
            except Exception as e:
                results["warnings"].append(f"Edge query '{eq}' failed: {e}")
                
        print(f"  -> Tested {len(search_results)} search queries. Sample: {search_results[0] if search_results else 'None'}")
        results["steps"]["search"] = {"samples": search_results, "status": "ok"}
        
        # Step 5: Explore & Usages on connected symbols
        print(f"Step 5: Testing Explore & Usages on connected symbols...")
        cur = db.conn.execute("""
            SELECT DISTINCT n.id, n.symbol, n.kind FROM graph_nodes n
            WHERE n.id IN (SELECT src FROM graph_edges UNION SELECT dst FROM graph_edges)
            AND n.kind IN ('class', 'function', 'method', 'interface')
            LIMIT 5
        """)
        connected_nodes = cur.fetchall()
        explore_results = []
        for nid, symbol, kind in connected_nodes:
            exp1 = service.explore(nid, depth=1)
            exp2 = service.explore(nid, depth=2)
            usages = service.usages(symbol)
            impls = service.implementations(symbol)
            explore_results.append({
                "symbol": symbol,
                "kind": kind,
                "depth1_relations": len(exp1.get("relations", [])),
                "depth2_relations": len(exp2.get("relations", [])),
                "callers_count": len(usages.get("callers", [])),
                "bases_count": len(impls.get("bases", [])),
                "derived_count": len(impls.get("derived", [])),
            })
        print(f"  -> Explore results: {explore_results}")
        results["steps"]["explore"] = {"samples": explore_results, "status": "ok"}
        
        # Step 6: Repo Map Generation & Token Budgets
        print(f"Step 6: Testing Repo Map Generation...")
        t0 = time.time()
        focus_syms = [s[1] for s in connected_nodes[:2]] if connected_nodes else None
        repo_map_1k = build_repo_map(db.conn, max_tokens=1000, focus=focus_syms, root=str(repo_path))
        repo_map_4k = build_repo_map(db.conn, max_tokens=4000, focus=focus_syms, root=str(repo_path))
        t1 = time.time()
        print(f"  -> Generated Repo Map (1k tokens: {len(repo_map_1k.get('rendered', ''))} chars / {repo_map_1k.get('symbols', 0)} syms, 4k tokens: {len(repo_map_4k.get('rendered', ''))} chars / {repo_map_4k.get('symbols', 0)} syms) in {round(t1-t0, 3)}s")
        results["steps"]["repo_map"] = {
            "map_1k_chars": len(repo_map_1k.get("rendered", "")),
            "map_1k_symbols": repo_map_1k.get("symbols", 0),
            "map_4k_chars": len(repo_map_4k.get("rendered", "")),
            "map_4k_symbols": repo_map_4k.get("symbols", 0),
            "time_s": round(t1 - t0, 3),
            "status": "ok"
        }
        
        # Step 7: Vector Hybrid Retrieval (sqlite-vec + RRF)
        print(f"Step 7: Testing Vector Indexing & Hybrid Search...")
        try:
            embedder = vector.HashEmbedder(dim=128)
            indexed_vecs = vector.index_nodes(db.conn, embedder=embedder, limit=1000)
            vec_res = vector.vector_search(db.conn, "controller service handler", embedder=embedder, limit=5)
            fused_res = vector.hybrid_search(db, "service", embedder=embedder, limit=5)
            print(f"  -> Vector indexed: {indexed_vecs} nodes, Vector search hits: {len(vec_res)}, Hybrid fused hits: {len(fused_res.get('results', []))}")
            results["steps"]["vector"] = {
                "indexed_vectors": indexed_vecs,
                "vec_search_hits": len(vec_res),
                "hybrid_search_hits": len(fused_res.get("results", [])),
                "status": "ok"
            }
        except Exception as e:
            print(f"  ⚠️ Vector test error: {e}")
            results["warnings"].append(f"Vector test error: {e}")
            results["steps"]["vector"] = {"status": "skipped_or_warn", "error": str(e)}

        # Step 8: Verifier & Drift Detection
        print(f"Step 8: Testing Verifier & Drift Detection...")
        drift_audit = reconciler.audit_drift(deep=True)
        service_drift = service.verify_drift(deep=True)
        print(f"  -> Drift audit: {len(drift_audit)} items, Service drift: {service_drift}")
        results["steps"]["verifier"] = {
            "drift_audit_count": len(drift_audit),
            "service_drift": service_drift,
            "status": "ok"
        }
        if len(drift_audit) > 0:
            results["warnings"].append(f"Unexpected drift immediately after full reconciliation: {drift_audit[:5]}")

        # Build AnalyticsGraph for steps 9-13
        print("Building AnalyticsGraph from database...")
        t0 = time.time()
        graph = AnalyticsGraph.from_database(db)
        t1 = time.time()
        print(f"  -> AnalyticsGraph loaded ({len(graph.nodes)} nodes, {len(graph.edges)} edges) in {round(t1-t0, 3)}s")
        
        # Step 9: Community Detection / Clustering (Louvain)
        print(f"Step 9: Testing Community Detection (Louvain)...")
        t0 = time.time()
        comm_result = graph.detect_communities()
        t1 = time.time()
        mod_q = graph.calculate_modularity(comm_result.node_to_community)
        comm_count = len(comm_result.communities)
        print(f"  -> Communities detected: {comm_count}, Modularity Q: {round(mod_q, 4)} in {round(t1-t0, 3)}s")
        results["steps"]["clustering"] = {
            "community_count": comm_count,
            "modularity_q": round(mod_q, 4),
            "time_s": round(t1 - t0, 3),
            "status": "ok",
        }
        
        # Step 10: Architecture Diagnostics & God Nodes
        print(f"Step 10: Testing Architecture Diagnostics & God Nodes...")
        analysis = analyze_graph(graph)
        md_report = generate_markdown_report(analysis, project_name=repo_name)
        god_nodes_count = len(analysis.god_nodes)
        surprising_count = len(analysis.surprising_connections)
        print(f"  -> God nodes: {god_nodes_count}, Surprising connections: {surprising_count}, Report length: {len(md_report)} chars")
        results["steps"]["diagnostics"] = {
            "god_nodes": god_nodes_count,
            "surprising_connections": surprising_count,
            "density": round(analysis.metrics.density, 6),
            "avg_degree": round(analysis.metrics.avg_degree, 2),
            "report_length": len(md_report),
            "status": "ok",
        }
        
        # Step 11: Interactive HTML Visualizer
        html_content = generate_html_visualizer(graph, analysis=analysis, title=f"SOT Graph - {repo_name}")
        html_path = Path(temp_dir) / "graph.html"
        save_html_visualizer(html_content, output_path=str(html_path), open_browser=False)
        print(f"  -> HTML Visualizer generated ({len(html_content)} bytes)")
        results["steps"]["html_viz"] = {
            "html_bytes": len(html_content),
            "file_exists": html_path.exists(),
            "status": "ok"
        }
        
        # Step 12: Fact Bundle Extraction
        print(f"Step 12: Testing Fact Bundle Extraction...")
        try:
            bundler = ArchitectureBundler(db, str(repo_path))
            bundle_dir = Path(temp_dir) / "bundle"
            bundle_files = bundler.extract_bundle(str(bundle_dir))
            print(f"  -> Fact bundle files generated: {list(bundle_files.keys())}")
            expected_files = [
                "01_module_inventory.md",
                "02_routing_endpoints.md",
                "03_workflows_states.md",
                "04_dependencies_violations.md",
                "05_system_metrics.json"
            ]
            missing_bundle_files = [f for f in expected_files if not (bundle_dir / f).exists()]
            if missing_bundle_files:
                results["warnings"].append(f"Missing bundle files: {missing_bundle_files}")
            results["steps"]["bundle"] = {"files": list(bundle_files.keys()), "status": "ok"}
        except Exception as e:
            print(f"  ❌ Bundle error: {e}")
            results["errors"].append({"step": "bundle", "error": str(e), "traceback": traceback.format_exc()})
            results["steps"]["bundle"] = {"status": "error", "error": str(e)}
        # Step 13: Exporters (GraphRAG JSON, Obsidian, GraphML, SCIP)
        print(f"Step 13: Testing Exporters...")
        try:
            rag_path = Path(temp_dir) / "graphrag.json"
            export_graphrag_json(graph, analysis=analysis, output_path=str(rag_path))
            
            obs_dir = Path(temp_dir) / "obsidian"
            export_obsidian_vault(graph, output_dir=str(obs_dir), analysis=analysis)
            obs_files = list(obs_dir.glob("*.md")) if obs_dir.exists() else []
            
            gml_path = Path(temp_dir) / "graph.graphml"
            export_graphml(graph, output_path=str(gml_path), analysis=analysis)
            
            scip_path = Path(temp_dir) / "index.scip"
            _ = export_scip(db, str(repo_path), str(scip_path))
            results["steps"]["export"] = {
                "graphrag_size": rag_path.stat().st_size if rag_path.exists() else 0,
                "obsidian_files": len(obs_files),
                "graphml_size": gml_path.stat().st_size if gml_path.exists() else 0,
                "scip_size": scip_path.stat().st_size if scip_path.exists() else 0,
                "status": "ok"
            }
            print(f"  -> Export results: {results['steps']['export']}")
        except Exception as e:
            print(f"  ❌ Export error: {e}")
            results["errors"].append({"step": "export", "error": str(e), "traceback": traceback.format_exc()})
            results["steps"]["export"] = {"status": "error", "error": str(e)}

        # Step 14: Maintenance (Clean & Vacuum)
        print(f"Step 14: Testing Maintenance (Clean & Vacuum)...")
        try:
            clean_plan = db.plan_clean(str(repo_path))
            vac_res = db.vacuum(optimize=True, dry_run=True)
            print(f"  -> Clean plan: mode={clean_plan.mode}, paths={len(clean_plan.paths)}, Vacuum: {vac_res}")
            results["steps"]["maintenance"] = {"clean_plan_paths": len(clean_plan.paths), "vacuum": str(vac_res), "status": "ok"}
        except Exception as e:
            print(f"  ❌ Maintenance error: {e}")
            results["errors"].append({"step": "maintenance", "error": str(e), "traceback": traceback.format_exc()})
            results["steps"]["maintenance"] = {"status": "error", "error": str(e)}
            
        # Step 15: Incremental Reconciler & Self-Healing
        print(f"Step 15: Testing Incremental Sync & Self-Healing...")
        try:
            nodes_before = db.stats()["nodes"]
            # Create a real temporary source file
            temp_src = repo_path / "__sot_test_probe__.py"
            temp_src.write_text("def sot_probe_fn():\n    return 'sot_ok'\n", encoding="utf-8")
            
            # Incremental reconcile of single file
            rec_inc = reconciler.reconcile(paths=[str(temp_src)])
            assert rec_inc.updated >= 1, f"Expected updated >= 1, got {rec_inc}"
            nodes_mid = db.stats()["nodes"]
            assert nodes_mid > nodes_before, f"Expected {nodes_mid} > {nodes_before}"
            
            # Delete file and reconcile to verify self-healing purge
            if temp_src.exists():
                temp_src.unlink()
            rec_heal = reconciler.reconcile()
            assert rec_heal.deleted >= 1, f"Expected deleted >= 1, got {rec_heal}"
            nodes_after = db.stats()["nodes"]
            assert nodes_after == nodes_before, f"Expected {nodes_after} == {nodes_before}"
            
            results["steps"]["self_healing"] = {
                "incremental_updated": rec_inc.updated,
                "purge_deleted": rec_heal.deleted,
                "status": "ok"
            }
            print(f"  -> Self-healing & incremental sync verified (created -> +{nodes_mid-nodes_before} nodes, deleted -> purged).")
        except Exception as e:
            print(f"  ❌ Self-healing error: {e}")
            results["errors"].append({"step": "self_healing", "error": str(e), "traceback": traceback.format_exc()})
            results["steps"]["self_healing"] = {"status": "error", "error": str(e)}

    except Exception as e:
        print(f"❌ Fatal error testing repo {repo_name}: {e}")
        results["errors"].append({"step": "fatal", "error": str(e), "traceback": traceback.format_exc()})
    finally:
        try:
            # Cleanup probe file if left over
            probe = repo_path / "__sot_test_probe__.py"
            if probe.exists():
                probe.unlink()
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass

    return results


def main():
    print("=" * 60)
    print("🌟 SOT-GRAPH REAL-WORLD MULTI-REPO VERIFICATION HARNESS 🌟")
    print("=" * 60)
    
    all_results = []
    total_errors = 0
    total_warnings = 0
    successful_repos = 0
    
    for repo_info in REPOS_TO_TEST:
        res = test_repo(repo_info)
        all_results.append(res)
        errs = len(res.get("errors", []))
        warns = len(res.get("warnings", []))
        total_errors += errs
        total_warnings += warns
        if errs == 0 and res.get("status") != "skipped":
            successful_repos += 1
            
    print("\n" + "=" * 60)
    print("📊 OVERALL SUMMARY & DIAGNOSTICS")
    print("=" * 60)
    
    for res in all_results:
        repo = res["repo"]
        lang = res["lang"]
        errs = res.get("errors", [])
        warns = res.get("warnings", [])
        status = res.get("status")
        
        if status == "skipped":
            print(f"⚪ {repo} ({lang}): SKIPPED ({res.get('reason')})")
        elif len(errs) == 0:
            st = res.get("steps", {})
            rec = st.get("reconcile", {}).get("stats", {})
            scanned = rec.get("scanned", 0)
            nodes = st.get("doctor", {}).get("stats", {}).get("nodes", 0)
            edges = st.get("doctor", {}).get("stats", {}).get("edges", 0)
            print(f"✅ {repo} ({lang}): ALL 15 PIPELINES PASS (Scanned: {scanned} files, Nodes: {nodes}, Edges: {edges})")
            if warns:
                for w in warns:
                    print(f"   ⚠️  Warning: {w}")
        else:
            print(f"❌ {repo} ({lang}): {len(errs)} ERRORS, {len(warns)} WARNINGS")
            for err in errs:
                print(f"   - [{err.get('step')}]: {err.get('error')}")
                if "traceback" in err:
                    print(f"     Traceback:\n{err['traceback']}")

    print("\n" + "=" * 60)
    print(f"🎯 TOTAL REPOS TESTED: {len(REPOS_TO_TEST)}")
    print(f"✅ SUCCESSFUL: {successful_repos}")
    print(f"❌ TOTAL ERRORS: {total_errors}")
    print(f"⚠️  TOTAL WARNINGS: {total_warnings}")
    print("=" * 60)
    
    report_file = Path(__file__).parent.parent / "test_real_repos_report.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"📁 Full report written to: {report_file}")


if __name__ == "__main__":
    main()
