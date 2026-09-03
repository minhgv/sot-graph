from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sot_graph.analytics.graph import AnalyticsGraph
from sot_graph.cli import build_parser, cmd_export, cmd_viz
from sot_graph.db import Database
from sot_graph.export.exporter import (
    export_graphml,
    export_graphrag_json,
    export_obsidian_vault,
)
from sot_graph.export.html import generate_html_visualizer, save_html_visualizer
from sot_graph.reconciler import Reconciler


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="sot_test_export_")
        self.project_dir = Path(self.temp_dir) / "project"
        self.project_dir.mkdir(parents=True)
        self.db_path = str(self.project_dir / ".sot" / "sot.db")

        # Create sample files
        (self.project_dir / "auth.py").write_text(
            "def login(user, pw):\n    return verify_token(pw)\n\ndef verify_token(t):\n    return True\n",
            encoding="utf-8",
        )
        (self.project_dir / "api.py").write_text(
            "from auth import login\ndef handle_request(req):\n    return login(req.user, req.pw)\n",
            encoding="utf-8",
        )

        self.db = Database(self.db_path)
        self.reconciler = Reconciler(self.db, str(self.project_dir))
        self.reconciler.reconcile()

    def tearDown(self) -> None:
        self.db.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_html_visualizer_generation_and_save(self) -> None:
        graph = AnalyticsGraph.from_database(self.db)
        html = generate_html_visualizer(graph, title="Test Project Knowledge Graph")

        self.assertIn("<!DOCTYPE html>", html)
        self.assertIn("Test Project Knowledge Graph", html)
        # d3 must be inlined from the vendored bundle, never fetched from
        # the CDN (offline viewers used to get a silently dead page).
        self.assertIn("Copyright 2010-2023 Mike Bostock", html)
        self.assertNotIn('<script src="https://d3js.org', html)
        self.assertIn("const DATA = ", html)
        self.assertIn("login", html)
        self.assertIn("handle_request", html)

        out_path = str(self.project_dir / "graph.html")
        saved = save_html_visualizer(html, output_path=out_path, open_browser=False)
        self.assertEqual(saved, out_path)
        self.assertTrue(Path(out_path).exists())
        self.assertGreater(Path(out_path).stat().st_size, 500)
    def test_html_visualizer_escapes_hostile_metadata(self) -> None:
        graph = AnalyticsGraph()
        graph.add_node(
            "hostile",
            label='</script><img src=x onerror="alert(1)">',
            path='</div><script>alert("path")</script>',
            kind="function",
        )
        html = generate_html_visualizer(
            graph, title='</title><script>alert("title")</script>'
        )

        self.assertIn(
            "&lt;/title&gt;&lt;script&gt;alert(&quot;title&quot;)&lt;/script&gt;",
            html,
        )
        self.assertIn(r"\u003c/script\u003e", html)
        self.assertNotIn("<script>alert(", html)
        # The PAGE'S OWN code must never route data through innerHTML. The
        # inlined d3 library legitimately contains that identifier, so the
        # assertion is scoped to the app script after the DATA injection.
        app_script = html.split("const DATA = ", 1)[1]
        self.assertNotIn("innerHTML", app_script)


    def test_graphrag_json_export(self) -> None:
        graph = AnalyticsGraph.from_database(self.db)
        out_path = str(self.project_dir / "graphrag.json")
        data = export_graphrag_json(graph, output_path=out_path)

        self.assertIn("version", data)
        self.assertIn("metadata", data)
        self.assertIn("entities", data)
        self.assertIn("relationships", data)
        self.assertIn("communities", data)
        self.assertGreater(len(data["entities"]), 0)

        # Verify on-disk JSON
        self.assertTrue(Path(out_path).exists())
        disk_data = json.loads(Path(out_path).read_text(encoding="utf-8"))
        self.assertEqual(disk_data["version"], "1.0.0")
        self.assertEqual(len(disk_data["entities"]), len(data["entities"]))

    def test_obsidian_vault_export(self) -> None:
        graph = AnalyticsGraph.from_database(self.db)
        out_dir = str(self.project_dir / "obsidian_vault")
        count = export_obsidian_vault(graph, output_dir=out_dir)

        self.assertGreater(count, 3)
        vault_path = Path(out_dir)
        self.assertTrue(vault_path.is_dir())

        # Check Index.md
        index_file = vault_path / "Index.md"
        self.assertTrue(index_file.exists())
        index_content = index_file.read_text(encoding="utf-8")
        self.assertIn("# Knowledge Graph Index", index_content)
        self.assertIn("[[Community_", index_content)

        # Check markdown wikilinks inside entity files
        md_files = list(vault_path.glob("*.md"))
        self.assertEqual(len(md_files), count)
        for f in md_files:
            text = f.read_text(encoding="utf-8")
            self.assertIn("---", text)

    def test_obsidian_vault_collision_suffix(self) -> None:
        """Two node ids sanitizing to the same filename must both survive.

        "a/b/handler" and "a_b_handler" collapse to the same safe name;
        the second note used to silently overwrite the first and links
        pointed at the wrong note. G10 adds deterministic -2 suffixes.
        """
        graph = AnalyticsGraph()
        graph.add_node("a/b/handler", label="Handler A", kind="symbol",
                       path="a/b/handler.py", line_start=1)
        graph.add_node("a_b_handler", label="Handler B", kind="symbol",
                       path="c.py", line_start=1)
        graph.add_edge("a/b/handler", "a_b_handler", relation="calls")

        out_dir = str(self.project_dir / "obsidian_collide")
        export_obsidian_vault(graph, output_dir=out_dir)

        vault = Path(out_dir)
        self.assertTrue((vault / "a_b_handler.md").exists())
        self.assertTrue((vault / "a_b_handler-2.md").exists())
        # The disambiguated name is what wikilinks must reference.
        first = (vault / "a_b_handler.md").read_text(encoding="utf-8")
        self.assertIn("[[a_b_handler-2|Handler B]]", first)

    def test_graphml_export(self) -> None:
        graph = AnalyticsGraph.from_database(self.db)
        out_path = str(self.project_dir / "graph.graphml")
        export_graphml(graph, output_path=out_path)

        self.assertTrue(Path(out_path).exists())
        content = Path(out_path).read_text(encoding="utf-8")
        self.assertIn('<?xml version="1.0" encoding="UTF-8"?>', content)
        self.assertIn('<graphml xmlns="http://graphml.graphdrawing.org/xmlns">', content)
        self.assertIn('<graph id="sot_graph" edgedefault="directed">', content)
        self.assertIn('<node id=', content)

    def test_cli_viz_and_export_commands(self) -> None:
        parser = build_parser()

        # Test sot viz
        html_out = str(self.project_dir / "test_viz.html")
        args_viz = parser.parse_args(["--root", str(self.project_dir), "viz", "-o", html_out])
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_viz(args_viz, self.db, str(self.project_dir))
        self.assertEqual(ret, 0)
        self.assertTrue(Path(html_out).exists())

        # Test sot export --format graphrag
        rag_out = str(self.project_dir / "rag_cli.json")
        args_rag = parser.parse_args(["export", "-f", "graphrag", "-o", rag_out])
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_export(args_rag, self.db, str(self.project_dir))
        self.assertEqual(ret, 0)
        self.assertTrue(Path(rag_out).exists())

        # Test sot export --format obsidian
        obs_out = str(self.project_dir / "obs_cli")
        args_obs = parser.parse_args(["export", "-f", "obsidian", "-o", obs_out])
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_export(args_obs, self.db, str(self.project_dir))
        self.assertEqual(ret, 0)
        self.assertTrue(Path(obs_out).is_dir())

        # Test sot export --format graphml
        gml_out = str(self.project_dir / "gml_cli.graphml")
        args_gml = parser.parse_args(["export", "-f", "graphml", "-o", gml_out])
        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = cmd_export(args_gml, self.db, str(self.project_dir))
        self.assertEqual(ret, 0)
        self.assertTrue(Path(gml_out).exists())


if __name__ == "__main__":
    unittest.main()
