from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cotw import schema
from cotw.paths import COUNTRIES, OVERRIDES, REGION_TAGS


@pytest.fixture(scope="session")
def entries() -> dict[Path, dict]:
    return schema.load_all(COUNTRIES)


@pytest.fixture(scope="session")
def by_id(entries) -> dict[str, dict]:
    return {e["id"]: e for e in entries.values()}


@pytest.fixture(scope="session")
def exceptions() -> dict:
    path = OVERRIDES / "exceptions.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}


@pytest.fixture(scope="session")
def taxonomy() -> set[tuple[str, ...]]:
    return schema.load_regions_taxonomy(REGION_TAGS)
