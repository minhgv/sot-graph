import tempfile
import unittest
from pathlib import Path
from sot_graph.db import Database
from sot_graph.reconciler import Reconciler


class PythonSemanticResolverTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self._tmpdir.name)
        self.db_path = self.root / ".sot" / "sot.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = Database(str(self.db_path))

    def tearDown(self):
        self.db.close()
        self._tmpdir.cleanup()

    def write(self, rel_path: str, content: str) -> str:
        p = self.root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return str(p)

    def test_multi_level_relative_imports_and_aliases(self):
        # pkg/core/calculator.py
        self.write(
            "pkg/core/calculator.py",
            """\
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b
""",
        )
        # pkg/services/billing.py
        self.write(
            "pkg/services/billing.py",
            """\
from ..core.calculator import add as my_add, multiply as my_mul

def compute_total(price: int, qty: int, tax: int) -> int:
    subtotal = my_mul(price, qty)
    return my_add(subtotal, tax)
""",
        )
        Reconciler(self.db, str(self.root)).reconcile()

        # Check that edges from compute_total to add and multiply are resolved in graph_edges
        edges = self.db.conn.execute(
            """
            SELECT e.src, n2.symbol, e.relation
            FROM graph_edges e
            JOIN graph_nodes n1 ON e.src = n1.id
            JOIN graph_nodes n2 ON e.dst = n2.id
            WHERE n1.symbol = 'compute_total'
            """
        ).fetchall()

        called_symbols = {row[1] for row in edges}
        self.assertIn("add", called_symbols, f"my_add alias must resolve to add: {edges}")
        self.assertIn("multiply", called_symbols, f"my_mul alias must resolve to multiply: {edges}")

    def test_reexport_via_package_init(self):
        # pkg/internal/engine.py
        self.write(
            "pkg/internal/engine.py",
            """\
class DataEngine:
    def execute(self, query: str) -> str:
        return f"result: {query}"
""",
        )
        # pkg/__init__.py (re-exporting DataEngine)
        self.write(
            "pkg/__init__.py",
            """\
from .internal.engine import DataEngine

__all__ = ["DataEngine"]
""",
        )
        # app/main.py (importing from pkg directly)
        self.write(
            "app/main.py",
            """\
from pkg import DataEngine

def run_app():
    engine = DataEngine()
    return engine.execute("SELECT 1")
""",
        )
        Reconciler(self.db, str(self.root)).reconcile()

        edges = self.db.conn.execute(
            """
            SELECT n1.symbol, n2.symbol, e.relation
            FROM graph_edges e
            JOIN graph_nodes n1 ON e.src = n1.id
            JOIN graph_nodes n2 ON e.dst = n2.id
            WHERE n1.symbol = 'run_app'
            """
        ).fetchall()

        target_symbols = {row[1] for row in edges}
        self.assertIn("DataEngine", target_symbols, "DataEngine constructor call must resolve via __init__.py re-export")
        self.assertIn("DataEngine.execute", target_symbols, "Method execute on DataEngine must resolve")

    def test_mro_and_class_inheritance_resolution(self):
        # core/base_repo.py
        self.write(
            "core/base_repo.py",
            """\
class BaseRepository:
    def find_by_id(self, item_id: int):
        return f"item:{item_id}"
""",
        )
        # core/user_repo.py
        self.write(
            "core/user_repo.py",
            """\
from .base_repo import BaseRepository

class UserRepository(BaseRepository):
    def get_user(self, user_id: int):
        return self.find_by_id(user_id)
""",
        )
        # service/user_service.py
        self.write(
            "service/user_service.py",
            """\
from core.user_repo import UserRepository

def fetch_user_data(user_id: int):
    repo = UserRepository()
    return repo.find_by_id(user_id)
""",
        )
        Reconciler(self.db, str(self.root)).reconcile()

        # 1. self.find_by_id inside UserRepository.get_user must resolve to BaseRepository.find_by_id
        repo_edges = self.db.conn.execute(
            """
            SELECT n1.symbol, n2.symbol, e.relation
            FROM graph_edges e
            JOIN graph_nodes n1 ON e.src = n1.id
            JOIN graph_nodes n2 ON e.dst = n2.id
            WHERE n1.symbol = 'UserRepository.get_user'
            """
        ).fetchall()
        repo_targets = {row[1] for row in repo_edges}
        self.assertIn("BaseRepository.find_by_id", repo_targets,
                      f"Inherited method call in subclass must resolve to BaseRepository.find_by_id: {repo_edges}")

        # 2. repo.find_by_id inside fetch_user_data must resolve to BaseRepository.find_by_id via UserRepository MRO
        service_edges = self.db.conn.execute(
            """
            SELECT n1.symbol, n2.symbol, e.relation
            FROM graph_edges e
            JOIN graph_nodes n1 ON e.src = n1.id
            JOIN graph_nodes n2 ON e.dst = n2.id
            WHERE n1.symbol = 'fetch_user_data'
            """
        ).fetchall()
        service_targets = {row[1] for row in service_edges}
        self.assertIn("UserRepository", service_targets, "UserRepository constructor must resolve")
        self.assertIn("BaseRepository.find_by_id", service_targets,
                      f"MRO method call on subclass instance must resolve to BaseRepository.find_by_id: {service_edges}")

    def test_typed_annotation_and_receiver_inference(self):
        self.write(
            "lib/auth.py",
            """\
class Authenticator:
    def verify_token(self, token: str) -> bool:
        return len(token) > 10
""",
        )
        self.write(
            "handlers/auth_handler.py",
            """\
from lib.auth import Authenticator

def handle_login(token: str, auth: Authenticator) -> bool:
    return auth.verify_token(token)
""",
        )
        Reconciler(self.db, str(self.root)).reconcile()

        edges = self.db.conn.execute(
            """
            SELECT n1.symbol, n2.symbol, e.relation
            FROM graph_edges e
            JOIN graph_nodes n1 ON e.src = n1.id
            JOIN graph_nodes n2 ON e.dst = n2.id
            WHERE n1.symbol = 'handle_login'
            """
        ).fetchall()
        target_symbols = {row[1] for row in edges}
        self.assertIn("Authenticator.verify_token", target_symbols,
                      f"Parameter typed method call must resolve to Authenticator.verify_token: {edges}")


if __name__ == "__main__":
    unittest.main()
