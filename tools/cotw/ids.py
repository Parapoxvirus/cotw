"""Frozen COTW IDs.

``data/ids.yaml`` is the ledger: once an ID is assigned it never changes and is never
reused. The first assignment sorts all entries alphabetically by EN name (accent- and
case-insensitive); later entries get the next free number.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .paths import IDS_FILE
from .source import SourceEntry, slugify, sort_key

HEADER = (
    "# Frozen COTW IDs (DECISIONS.md A1). Assigned once, never changed, never reused.\n"
    "# New entries are appended with the next free number.\n"
)


def load(path: Path = IDS_FILE) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): v for k, v in data.items()}


def save(ledger: dict[str, dict], path: Path = IDS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(dict(sorted(ledger.items())), allow_unicode=True, sort_keys=False, width=100)
    path.write_text(HEADER + body, encoding="utf-8")


def format_id(n: int) -> str:
    return f"{n:03d}"


def assign(entries: list[SourceEntry], qids: dict[str, str], ledger: dict[str, dict]) -> dict[str, str]:
    """Return ``iso2 → id`` for all entries, extending the ledger in place for new ones.

    Matching order: Wikidata QID (survives ISO changes), then ISO-2.
    """
    by_qid = {v.get("wikidata"): k for k, v in ledger.items() if v.get("wikidata")}
    by_iso = {v["iso2"]: k for k, v in ledger.items()}
    result: dict[str, str] = {}
    new = []
    for e in entries:
        qid = qids.get(e.iso2)
        cid = by_qid.get(qid) or by_iso.get(e.iso2)
        if cid:
            result[e.iso2] = cid
        else:
            new.append(e)
    next_n = max((int(k) for k in ledger), default=0) + 1
    for e in sorted(new, key=lambda e: sort_key(e.name_en)):
        cid = format_id(next_n)
        next_n += 1
        ledger[cid] = {"slug": slugify(e.name_en), "iso2": e.iso2, "wikidata": qids.get(e.iso2)}
        result[e.iso2] = cid
    return result
