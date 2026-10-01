"""Repository paths. Everything is relative to the repo root so the tools work from any cwd."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
COUNTRIES = DATA / "countries"
IDS_FILE = DATA / "ids.yaml"
WIKIDATA = DATA / "wikidata"
DERIVED = DATA / "derived"
OVERRIDES = DATA / "overrides"
DOCS = ROOT / "docs"
REGION_TAGS = DATA / "tags.txt"
UI_ASSETS = ROOT / "assets" / "ui"

# Downloaded geodata lands here; the directory is gitignored (COTW_CACHE_DIR overrides it).
CACHE = Path(os.environ.get("COTW_CACHE_DIR", ROOT / ".cache"))
MEDIA = ROOT / "media"
STYLE = DATA / "style"
BUILD = ROOT / "build"
