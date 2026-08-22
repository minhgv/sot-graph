"""Phase 5: optional tree-sitter AST extractors (Go/Rust/Java/Kotlin/Swift)."""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sot_graph.extractor import parse_file_graph
from sot_graph.ts_extract import available_languages

LANGS = available_languages()

FIXTURES = {
    "go": (".go", '''package main

import "fmt"

type Server struct{}

func (s *Server) Handle() {
	fmt.Println("x")
}

func helper() int { return 1 }

func main() {
	s := &Server{}
	s.Handle()
}
'''),
    "rust": (".rs", '''pub struct Cache;

impl Cache {
    pub fn get(&self, k: &str) -> Option<&str> { None }
}

fn main() {
    let c = Cache;
    c.get("k");
}
'''),
    "java": (".java", '''import java.util.List;

public class Greeter {
    public String greet(String name) {
        return helper(name);
    }
    private String helper(String n) { return n; }
}
'''),
    "kotlin": (".kt", '''import kotlin.math.max

class Calc {
    fun double(x: Int): Int = twice(x)
    private fun twice(x: Int): Int = x * 2
}

fun main() {
    val c = Calc()
    c.double(1)
}
'''),
    "swift": (".swift", '''import Foundation

class Greeter {
    func greet(_ name: String) -> String {
        return "hi " + name
    }
}

let g = Greeter()
g.greet("x")
'''),
}

EXPECTED_NODES = {
    "go": ["Server", "Server.Handle", "helper", "main"],
    "rust": ["Cache", "get", "main"],
    "java": ["Greeter", "Greeter.greet", "Greeter.helper"],
    "kotlin": ["Calc", "Calc.double", "Calc.twice", "main"],
    "swift": ["Greeter", "Greeter.greet"],
}


class TreeSitterExtractionTests(unittest.TestCase):
    def _parse(self, language):
        ext, code = FIXTURES[language]
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        root = Path(directory)
        (root / "src").mkdir()
        target = root / "src" / f"sample{ext}"
        target.write_text(code, encoding="utf-8")
        return parse_file_graph(str(target), str(root))

    def test_available_languages_reported(self):
        # At least the grammars installed for development must be detected.
        if os.environ.get("SOT_TS_SKIP_UNAVAILABLE"):
            self.skipTest("tree-sitter extra not installed")
        self.assertTrue(any(LANGS.values()))

    def test_definitions_and_signatures_extracted(self):
        for language, expected in EXPECTED_NODES.items():
            with self.subTest(language=language):
                if not LANGS.get(language):
                    self.skipTest(f"grammar for {language} not installed")
                parsed = self._parse(language)
                self.assertIsNone(parsed["error"])
                ids = {n["symbol"] for n in parsed["nodes"] if n["kind"] != "file"}
                for symbol in expected:
                    self.assertIn(symbol, ids)
                symbols = [n for n in parsed["nodes"] if n["symbol"] in expected]
                self.assertTrue(all(s.get("signature") for s in symbols))

    def test_calls_and_imports_flow_into_graph_pipeline(self):
        for language in ("go", "java", "kotlin", "swift", "rust"):
            with self.subTest(language=language):
                if not LANGS.get(language):
                    self.skipTest(f"grammar for {language} not installed")
                parsed = self._parse(language)
                calls = [e for e in parsed["edges"] if e["relation"] == "calls"]
                pending_calls = [p for p in parsed["pending"] if p["relation"] == "calls"]
                # Intra-file BARE calls resolve to edges; receiver-qualified
                # calls stay pending as honest unresolved candidates.
                self.assertTrue(calls or pending_calls,
                                "expected call evidence in edges or pending")
                defines = [e for e in parsed["edges"] if e["relation"] == "defines"]
                self.assertTrue(defines)

    def test_java_intra_file_call_resolves(self):
        if not LANGS.get("java"):
            self.skipTest("grammar for java not installed")
        parsed = self._parse("java")
        calls = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1])
                 for e in parsed["edges"] if e["relation"] == "calls"}
        self.assertIn(("Greeter.greet", "Greeter.helper"), calls)

    def test_go_method_qualified_by_receiver_type(self):
        if not LANGS.get("go"):
            self.skipTest("grammar for go not installed")
        parsed = self._parse("go")
        ids = {n["symbol"] for n in parsed["nodes"] if n["kind"] != "file"}
        self.assertIn("Server.Handle", ids)


if __name__ == "__main__":
    unittest.main()
