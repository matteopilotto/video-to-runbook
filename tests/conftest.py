import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures" / "sap"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("GEMINI_API_KEY"):
        return
    skip = pytest.mark.skip(reason="GEMINI_API_KEY is not set")
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip)
