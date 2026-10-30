"""Live upstream checks are opt-in: set IZMIR_LIVE=1. They never run in CI by default."""
from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.getenv("IZMIR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="Set IZMIR_LIVE=1 to run live İzmir upstream checks.")
    for item in items:
        if "tests/live/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip)
