"""Phase 5: tree-sitter AST extractors (Go/Rust/Java/Kotlin/Swift/PHP/TypeScript/JavaScript/Python/C#)."""
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
    "php": (".php", '''<?php
namespace App\\Services;

use App\\Contracts\\PaymentInterface;
use App\\Traits\\LoggerTrait;

#[Attribute]
class RouteAttribute {}

#[RouteAttribute]
enum PaymentStatus: string implements Stringable {
    case PENDING = 'pending';
    case SUCCESS = 'success';
}

class PaymentService extends BaseService implements PaymentInterface {
    use LoggerTrait;

    public function process(Order $order): bool {
        $this->logInfo("Processing order");
        return true;
    }
}
'''),
    "typescript": (".ts", '''import { User } from "./models";

export interface IUserService {
    find(id: string): User;
}

export type UserId = string | number;

export enum UserRole {
    ADMIN = "ADMIN",
    USER = "USER"
}

export class UserService implements IUserService {
    public find(id: string): User {
        return this.fetchUser(id);
    }
    private fetchUser(id: string): User {
        return { id } as User;
    }
}

export const calculateTax = (amount: number): number => {
    return amount * 0.1;
};
'''),
    "javascript": (".js", '''import config from "./config";

export class ApiClient {
    async request(url) {
        return this.send(url);
    }
    async send(url) {
        return fetch(url);
    }
}

export const helper = (x) => x + 1;
'''),
    "python": (".py", '''from typing import Optional

type UserIdentifier = str | int

class BaseHandler:
    pass

class AuthHandler(BaseHandler):
    async def authenticate(self, token: str) -> bool:
        return self.verify(token)

    def verify(self, token: str) -> bool:
        return len(token) > 0
'''),
    "c_sharp": (".cs", '''using System;
using System.Threading.Tasks;

namespace App.Services;

public interface IOrderService {
    Task<bool> SubmitAsync(int id);
}

public record OrderDto(int Id, string Customer);

public class OrderService : BaseService, IOrderService {
    public async Task<bool> SubmitAsync(int id) {
        return await this.ProcessAsync(id);
    }
    private async Task<bool> ProcessAsync(int id) {
        return true;
    }
}
'''),
}

EXPECTED_NODES = {
    "go": ["Server", "Server.Handle", "helper", "main"],
    "rust": ["Cache", "get", "main"],
    "java": ["Greeter", "Greeter.greet", "Greeter.helper"],
    "kotlin": ["Calc", "Calc.double", "Calc.twice", "main"],
    "swift": ["Greeter", "Greeter.greet"],
    "php": ["PaymentStatus", "PaymentService", "PaymentService.process"],
    "typescript": ["IUserService", "UserId", "UserRole", "UserService", "UserService.find", "UserService.fetchUser", "calculateTax"],
    "javascript": ["ApiClient", "ApiClient.request", "ApiClient.send", "helper"],
    "python": ["UserIdentifier", "BaseHandler", "AuthHandler", "AuthHandler.authenticate", "AuthHandler.verify"],
    "c_sharp": ["IOrderService", "OrderDto", "OrderService", "OrderService.SubmitAsync", "OrderService.ProcessAsync"],
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
        if not any(LANGS.values()) or os.environ.get("SOT_TS_SKIP_UNAVAILABLE"):
            self.skipTest("tree-sitter extra grammars not installed")
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
        for language in ("go", "java", "kotlin", "swift", "rust", "php", "typescript", "javascript", "python", "c_sharp"):
            with self.subTest(language=language):
                if not LANGS.get(language):
                    self.skipTest(f"grammar for {language} not installed")
                parsed = self._parse(language)
                calls = [e for e in parsed["edges"] if e["relation"] == "calls"]
                pending_calls = [p for p in parsed["pending"] if p["relation"] == "calls"]
                # Intra-file BARE calls resolve to edges; receiver-qualified
                # calls stay pending as honest unresolved candidates.
                self.assertTrue(calls or pending_calls,
                                f"expected call evidence in edges or pending for {language}")
                defines = [e for e in parsed["edges"] if e["relation"] == "defines"]
                self.assertTrue(defines)

    def test_java_intra_file_call_resolves(self):
        if not LANGS.get("java"):
            self.skipTest("grammar for java not installed")
        parsed = self._parse("java")
        calls = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1])
                 for e in parsed["edges"] if e["relation"] == "calls"}
        self.assertIn(("Greeter.greet", "Greeter.helper"), calls)

    def test_java_inheritance_edges_extracted(self):
        if not LANGS.get("java"):
            self.skipTest("grammar for java not installed")
        code = '''package p;

public interface MpsService {}

public interface Combo extends MpsService {}

public class BaseService {}

public class MpsServiceImpl extends BaseService
        implements MpsService, Combo {}

public class GenericRepo extends java.util.AbstractMap<String, String>
        implements MpsService {}
'''
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        target = Path(directory) / "sample.java"
        target.write_text(code, encoding="utf-8")
        parsed = parse_file_graph(str(target), directory)
        pending_rel = {(p["src"].rsplit(":", 1)[-1], p["dst_symbol"], p["relation"])
                       for p in parsed["pending"]}
        edge_rel = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1], e["relation"])
                    for e in parsed["edges"]}
        found = {(s, d, r) for s, d, r in pending_rel | edge_rel
                 if r in ("extends", "implements")}
        self.assertIn(("MpsServiceImpl", "BaseService", "extends"), found)
        self.assertIn(("MpsServiceImpl", "MpsService", "implements"), found)
        self.assertIn(("MpsServiceImpl", "Combo", "implements"), found)
        self.assertIn(("Combo", "MpsService", "extends"), found)
        self.assertIn(("GenericRepo", "AbstractMap", "extends"), found)
        self.assertIn(("GenericRepo", "MpsService", "implements"), found)

    def test_php_inheritance_and_trait_edges_extracted(self):
        if not LANGS.get("php"):
            self.skipTest("grammar for php not installed")
        parsed = self._parse("php")
        pending_rel = {(p["src"].rsplit(":", 1)[-1], p["dst_symbol"], p["relation"])
                       for p in parsed["pending"]}
        edge_rel = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1], e["relation"])
                    for e in parsed["edges"]}
        found = {(s, d, r) for s, d, r in pending_rel | edge_rel
                 if r in ("extends", "implements", "uses")}
        self.assertIn(("PaymentService", "BaseService", "extends"), found)
        self.assertIn(("PaymentService", "PaymentInterface", "implements"), found)
        self.assertTrue(
            ("PaymentService", "LoggerTrait", "uses") in found
            or ("PaymentService", "LoggerTrait", "implements") in found
        )
        self.assertIn(("PaymentStatus", "Stringable", "implements"), found)

    def test_typescript_inheritance_extracted(self):
        if not LANGS.get("typescript"):
            self.skipTest("grammar for typescript not installed")
        parsed = self._parse("typescript")
        pending_rel = {(p["src"].rsplit(":", 1)[-1], p["dst_symbol"], p["relation"])
                       for p in parsed["pending"]}
        edge_rel = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1], e["relation"])
                    for e in parsed["edges"]}
        found = {(s, d, r) for s, d, r in pending_rel | edge_rel
                 if r in ("extends", "implements")}
        self.assertIn(("UserService", "IUserService", "implements"), found)

    def test_c_sharp_inheritance_extracted(self):
        if not LANGS.get("c_sharp"):
            self.skipTest("grammar for c_sharp not installed")
        parsed = self._parse("c_sharp")
        pending_rel = {(p["src"].rsplit(":", 1)[-1], p["dst_symbol"], p["relation"])
                       for p in parsed["pending"]}
        edge_rel = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1], e["relation"])
                    for e in parsed["edges"]}
        found = {(s, d, r) for s, d, r in pending_rel | edge_rel
                 if r in ("extends", "implements")}
        self.assertIn(("OrderService", "BaseService", "extends"), found)
        self.assertIn(("OrderService", "IOrderService", "extends"), found)

    def test_python_inheritance_extracted(self):
        if not LANGS.get("python"):
            self.skipTest("grammar for python not installed")
        parsed = self._parse("python")
        pending_rel = {(p["src"].rsplit(":", 1)[-1], p["dst_symbol"], p["relation"])
                       for p in parsed["pending"]}
        edge_rel = {(e["src"].rsplit(":", 1)[-1], e["dst"].rsplit(":", 1)[-1], e["relation"])
                    for e in parsed["edges"]}
        found = {(s, d, r) for s, d, r in pending_rel | edge_rel
                 if r in ("extends", "implements")}
        self.assertIn(("AuthHandler", "BaseHandler", "extends"), found)

    def test_go_method_qualified_by_receiver_type(self):
        if not LANGS.get("go"):
            self.skipTest("grammar for go not installed")
        parsed = self._parse("go")
        ids = {n["symbol"] for n in parsed["nodes"] if n["kind"] != "file"}
        self.assertIn("Server.Handle", ids)


if __name__ == "__main__":
    unittest.main()
