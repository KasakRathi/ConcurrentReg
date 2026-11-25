"""pytest plugin: run the EXISTING, UNMODIFIED test suite with IASL really switched on.

The normal fixtures build servers with IASL explicitly OFF, so the existing suite never exercises the
hooks. This plugin wraps app.main.create_app so every server a test builds has IASL enabled with its
default (provisional) settings, and sets IASL_ENABLED=1 for the module-level app used by TestClient(app).

    PYTHONPATH=. TEST_DATABASE_URL=...  python -m pytest -p tests.iasl_enabled_plugin

SAFETY: it must set DATABASE_URL before app.main is imported (the engine is created at import), so it
repeats conftest's guard first: it refuses to run unless TEST_DATABASE_URL names a database ending in _test.
"""
import os

_url = os.environ.get("TEST_DATABASE_URL", "")
if not _url.rsplit("/", 1)[-1].endswith("_test"):
    raise RuntimeError("iasl_enabled_plugin: set TEST_DATABASE_URL to a database whose name ends with _test.")
os.environ["DATABASE_URL"] = _url
os.environ.setdefault("IASL_ENABLED", "1")

from app import main  # noqa: E402
from app.iasl.config import IASLConfig  # noqa: E402

_original_create_app = main.create_app


def create_app(os_config=None, iasl_config=None):
    if iasl_config is None or not iasl_config.enabled:
        iasl_config = IASLConfig(enabled=True)      # every default: nothing tuned to help the tests pass
    return _original_create_app(os_config, iasl_config)


main.create_app = create_app


def pytest_report_header(config):
    return "IASL: ENABLED for every server built by this run (tests.iasl_enabled_plugin)"
