"""Invariant I5: IASL is isolated from the correctness-critical code, enforced by reading the source."""
import ast
import pathlib

IASL_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "iasl"
OS_LAYER_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "os_layer"

# IASL may not reach the registration transaction, the schema, the engine/sessions, the seed data,
# any SQL library, or the OS layer's code (it only reads the layer through duck typing).
FORBIDDEN_FOR_IASL = ("app.registration_service", "app.models", "app.database", "app.seed", "app.os_layer",
                      "sqlalchemy", "pymysql", "importlib")
FORBIDDEN_NAMES_FROM_APP = {"registration_service", "models", "database", "seed", "os_layer"}


def imports_of(source):
    """Every module an import statement in `source` could pull in, as dotted names."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            found.append(base)
            found += [f"{base}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("__import__", "exec", "eval"):
            found.append(f"<dynamic:{node.func.id}>")
    return found


def violations(source, forbidden=FORBIDDEN_FOR_IASL):
    bad = []
    for name in imports_of(source):
        if name.startswith("<dynamic:") or any(name == f or name.startswith(f + ".") for f in forbidden):
            bad.append(name)
    return sorted(set(bad))


def test_the_scanner_itself_catches_every_kind_of_forbidden_import():
    for snippet in ("import app.models", "from app.database import SessionLocal", "from app import registration_service",
                    "from app.models import Student", "import sqlalchemy", "from sqlalchemy.orm import Session",
                    "import pymysql", "from app.os_layer.request_pipeline import OSConcurrencyLayer",
                    "import importlib", "__import__('app.models')", "eval('1')"):
        assert violations(snippet), snippet
    assert not violations("import threading\nfrom collections import deque\nfrom app.iasl.types import Signal")


def test_nothing_in_app_iasl_imports_registration_database_or_sql_code():
    files = sorted(IASL_DIR.rglob("*.py"))
    assert len(files) >= 8, "the scan found suspiciously few IASL modules"
    problems = {str(f.relative_to(IASL_DIR.parent.parent)): violations(f.read_text()) for f in files}
    assert {name: bad for name, bad in problems.items() if bad} == {}


def test_the_os_layer_does_not_import_iasl_so_it_stays_usable_without_it():
    for f in sorted(OS_LAYER_DIR.rglob("*.py")):
        assert violations(f.read_text(), forbidden=("app.iasl",)) == [], f.name
