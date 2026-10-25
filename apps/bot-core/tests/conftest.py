"""Pytest configuration for Bot Core tests."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Never touch a real Turso database from tests.
os.environ["DB_BACKEND"] = "sqlite"
os.environ.pop("TURSO_URL", None)
os.environ.pop("TURSO_TOKEN", None)
