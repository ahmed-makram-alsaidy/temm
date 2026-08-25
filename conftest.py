"""Force pytest to use an isolated database, never the operator's TEMM store."""

import os
import tempfile
from pathlib import Path


def pytest_configure(config):
    production_dir = (Path.home() / ".ai_fleet").resolve()
    configured = os.environ.get("AI_FLEET_DATA_DIR")
    if configured and Path(configured).resolve() == production_dir:
        raise RuntimeError("Tests refuse to run against the production TEMM database.")
    test_dir = Path(tempfile.mkdtemp(prefix="ai-fleet-test-db-"))
    os.environ["AI_FLEET_DATA_DIR"] = str(test_dir)
    os.environ["AI_FLEET_TEST_DATABASE"] = "1"


def pytest_unconfigure(config):
    os.environ.pop("AI_FLEET_TEST_DATABASE", None)
