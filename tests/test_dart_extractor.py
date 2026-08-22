"""
tests.test_dart_extractor - Comprehensive unit test suite for Dart and Flutter AST/symbol extraction.
Exercises classes, widgets, mixins, extensions, enums, constructors, methods, getters/setters,
top-level functions, imports, cross-file pending edges, and reconciler integration.
"""

import tempfile
import unittest
from pathlib import Path

from sot_graph._vendor.graphify.extract import extract_dart
from sot_graph.db import Database
from sot_graph.extractor import parse_file_graph, EXT_DISPATCH, LANGUAGE_MAP
from sot_graph.reconciler import Reconciler


class TestDartExtractor(unittest.TestCase):
    """Test suite for extract_dart."""

    def test_registered_in_dispatch(self):
        """Verify .dart is properly registered in extractor dispatch and language mapping."""
        self.assertIn(".dart", EXT_DISPATCH)
        self.assertEqual(EXT_DISPATCH[".dart"], "extract_dart")
        self.assertEqual(LANGUAGE_MAP.get(".dart"), "dart")
        self.assertEqual(LANGUAGE_MAP.get(".arb"), "json")

    def test_extract_classes_and_widgets(self):
        """Test extraction of Flutter widgets (StatelessWidget, StatefulWidget, State)."""
        code = """
import 'package:flutter/material.dart';

class CustomButton extends StatelessWidget {
  final String title;
  final VoidCallback onPressed;

  const CustomButton({
    super.key,
    required this.title,
    required this.onPressed,
  });

  @override
  Widget build(BuildContext context) {
    return ElevatedButton(
      onPressed: onPressed,
      child: Text(title),
    );
  }
}

class UserCard extends StatefulWidget {
  final String userId;
  const UserCard({super.key, required this.userId});

  @override
  State<UserCard> createState() => _UserCardState();
}

class _UserCardState extends State<UserCard> {
  @override
  void initState() {
    super.initState();
    _loadUser();
  }

  void _loadUser() {}

  @override
  Widget build(BuildContext context) {
    return Container();
  }
}
"""
        with tempfile.NamedTemporaryFile(suffix=".dart", mode="w", delete=False) as f:
            f.write(code)
            f_path = Path(f.name)

        try:
            res = extract_dart(f_path)
            self.assertIsNone(res.get("error"))
            nodes = {n["id"]: n for n in res["nodes"]}
            edges = res["edges"]

            # Classes
            self.assertIn("CustomButton", nodes)
            self.assertEqual(nodes["CustomButton"]["kind"], "class")
            self.assertIn("UserCard", nodes)
            self.assertIn("_UserCardState", nodes)

            # Constructors & Methods
            self.assertIn("CustomButton.CustomButton", nodes)
            self.assertEqual(nodes["CustomButton.CustomButton"]["kind"], "constructor")
            self.assertIn("CustomButton.build", nodes)
            self.assertEqual(nodes["CustomButton.build"]["kind"], "method")
            self.assertIn("UserCard.createState", nodes)
            self.assertIn("_UserCardState.initState", nodes)
            self.assertIn("_UserCardState.build", nodes)

            # Inheritance edges
            extends_edges = [e for e in edges if e["relation"] == "extends"]
            self.assertTrue(any(e["source"] == "CustomButton" and e["target"] == "StatelessWidget" for e in extends_edges))
            self.assertTrue(any(e["source"] == "UserCard" and e["target"] == "StatefulWidget" for e in extends_edges))
            self.assertTrue(any(e["source"] == "_UserCardState" and e["target"] == "State" for e in extends_edges))

            # Imports
            import_edges = [e for e in edges if e["relation"] == "imports"]
            self.assertTrue(any("package:flutter/material.dart" in e["target"] for e in import_edges))
        finally:
            f_path.unlink(missing_ok=True)

    def test_extract_mixins_and_extensions(self):
        """Test extraction of Dart mixins and extensions."""
        code = """
mixin DiagnosticMixin on ChangeNotifier implements Diagnosticable {
  void logDiagnostic(String msg) {
    debugPrint(msg);
  }
}

extension StringValidation on String {
  bool get isValidEmail => contains('@');
  String toCapitalized() => isEmpty ? this : this[0].toUpperCase() + substring(1);
}
"""
        with tempfile.NamedTemporaryFile(suffix=".dart", mode="w", delete=False) as f:
            f.write(code)
            f_path = Path(f.name)

        try:
            res = extract_dart(f_path)
            nodes = {n["id"]: n for n in res["nodes"]}

            self.assertIn("DiagnosticMixin", nodes)
            self.assertEqual(nodes["DiagnosticMixin"]["kind"], "mixin")
            self.assertIn("DiagnosticMixin.logDiagnostic", nodes)

            self.assertIn("StringValidation", nodes)
            self.assertEqual(nodes["StringValidation"]["kind"], "extension")
            self.assertIn("StringValidation.isValidEmail", nodes)
            self.assertEqual(nodes["StringValidation.isValidEmail"]["kind"], "getter")
            self.assertIn("StringValidation.toCapitalized", nodes)
            self.assertEqual(nodes["StringValidation.toCapitalized"]["kind"], "method")
        finally:
            f_path.unlink(missing_ok=True)

    def test_extract_enums_and_getters_setters(self):
        """Test extraction of enums, getters, and setters."""
        code = """
enum AuthStatus {
  unauthenticated,
  authenticating,
  authenticated,
  failed,
}

class SessionStore {
  String? _token;

  String? get token => _token;

  set token(String? val) {
    _token = val;
  }

  bool get isAuthenticated => _token != null;
}
"""
        with tempfile.NamedTemporaryFile(suffix=".dart", mode="w", delete=False) as f:
            f.write(code)
            f_path = Path(f.name)

        try:
            res = extract_dart(f_path)
            nodes = {n["id"]: n for n in res["nodes"]}

            self.assertIn("AuthStatus", nodes)
            self.assertEqual(nodes["AuthStatus"]["kind"], "enum")

            self.assertIn("SessionStore", nodes)
            self.assertIn("SessionStore.token", nodes)
            self.assertEqual(nodes["SessionStore.token"]["kind"], "getter")
            self.assertIn("SessionStore.token=", nodes)
            self.assertEqual(nodes["SessionStore.token="]["kind"], "setter")
            self.assertIn("SessionStore.isAuthenticated", nodes)
            self.assertEqual(nodes["SessionStore.isAuthenticated"]["kind"], "getter")
        finally:
            f_path.unlink(missing_ok=True)

    def test_extract_top_level_functions(self):
        """Test extraction of top level standalone functions."""
        code = """
Future<String> fetchUserToken(String username, String password) async {
  return "token_123";
}

void showAppToast(String message) {
  print(message);
}
"""
        with tempfile.NamedTemporaryFile(suffix=".dart", mode="w", delete=False) as f:
            f.write(code)
            f_path = Path(f.name)

        try:
            res = extract_dart(f_path)
            nodes = {n["id"]: n for n in res["nodes"]}

            self.assertIn("fetchUserToken", nodes)
            self.assertEqual(nodes["fetchUserToken"]["kind"], "function")
            self.assertIn("showAppToast", nodes)
            self.assertEqual(nodes["showAppToast"]["kind"], "function")
        finally:
            f_path.unlink(missing_ok=True)

    def test_parse_file_graph_dart_integration(self):
        """Test full integration with sot_graph.extractor.parse_file_graph."""
        code = """
import 'package:http/http.dart' as http;

class ApiService {
  final String baseUrl;
  ApiService({required this.baseUrl});

  Future<void> login(String user) async {
    final client = http.Client();
  }
}
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            dart_file = root / "lib" / "api_service.dart"
            dart_file.parent.mkdir(parents=True, exist_ok=True)
            dart_file.write_text(code, encoding="utf-8")

            res = parse_file_graph(str(dart_file), str(root))
            self.assertIsNone(res.get("error"))
            self.assertGreater(len(res["nodes"]), 1)

            # Check file node
            file_nodes = [n for n in res["nodes"] if n["kind"] == "file"]
            self.assertEqual(len(file_nodes), 1)
            self.assertTrue(file_nodes[0]["id"].startswith("file:"))
            self.assertEqual(file_nodes[0]["label"], "File: lib/api_service.dart")

            # Check symbol nodes
            class_nodes = [n for n in res["nodes"] if n["kind"] == "class"]
            self.assertEqual(len(class_nodes), 1)
            self.assertTrue(class_nodes[0]["id"].startswith("sym:"))
            self.assertTrue(class_nodes[0]["id"].endswith(":ApiService"))

    def test_reconciler_indexes_dart_and_arb_files(self):
        """Test Reconciler end-to-end indexing of Dart and ARB files into SQLite database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / ".sot" / "sot.db"
            db = Database(str(db_path))

            # Create sample Flutter project structure
            lib_dir = root / "lib"
            lib_dir.mkdir(parents=True, exist_ok=True)
            
            main_dart = lib_dir / "main.dart"
            main_dart.write_text("""
import 'package:flutter/material.dart';
import 'home_page.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      home: HomePage(),
    );
  }
}
""", encoding="utf-8")

            home_page = lib_dir / "home_page.dart"
            home_page.write_text("""
import 'package:flutter/material.dart';

class HomePage extends StatelessWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Home')),
      body: const Center(child: Text('Hello Flutter')),
    );
  }
}
""", encoding="utf-8")

            l10n_dir = root / "lib" / "l10n"
            l10n_dir.mkdir(parents=True, exist_ok=True)
            app_en = l10n_dir / "app_en.arb"
            app_en.write_text('{"@@locale": "en", "hello": "Hello World"}', encoding="utf-8")

            reconciler = Reconciler(db, str(root))
            stats = reconciler.reconcile()

            self.assertEqual(stats.updated, 3)
            self.assertEqual(stats.failed, 0)

            # Search in SQLite
            results = db.search_fts("MyApp")
            self.assertGreater(len(results), 0)
            self.assertTrue(any("MyApp" in r.get("id", "") or "MyApp" in r.get("label", "") for r in results))

            # Check stats
            db_stats = db.stats()
            self.assertEqual(db_stats["paths"], 3)
            self.assertGreater(db_stats["nodes"], 0)


if __name__ == "__main__":
    unittest.main()
