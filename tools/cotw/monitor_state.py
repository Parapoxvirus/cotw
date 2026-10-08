"""Dedupe state of the Paperclip sink of the change monitor (docs/MONITORING.md).

Gitea issues carry their own state: the fingerprint marker in the body, open or closed. A
Paperclip task bridge key can create tasks and read the ones it created, but cannot list them,
so the monitor keeps what it filed in one JSON file on a dedicated branch of the repository,
read and written through the Gitea contents API:

```json
{"version": 2,
 "filed":   {"<fingerprint>": {"task_id", "identifier", "title", "filed_at"}},
 "decided": {"<fingerprint>": {"source", "decided_at"}},
 "summary": {"task_id", "identifier"} | null,
 "names":   {"<qid>": {"labels/<code>": "<label>" | null, "P1448": ["<code>: <name>", …]}},
 "sources": {"<source id>": {"signature": {…}, "since", "failures", "failing_since"}}}
```

``filed`` tasks are still being worked on; ``decided`` fingerprints are never filed again (a
closed or cancelled task, like a closed issue). ``names`` and ``sources`` are the baselines of
the name and naming-source checks (``monitor_watch``): the Wikidata values and source
signatures last seen, not COTW's names. A version 1 file loads with both empty.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_BRANCH = "cotw-monitor-state"
STATE_FILE = "cotw-monitor-state.json"
VERSION = 2
READABLE = (1, 2)  # version 1: no names/sources baseline yet


def state_branch() -> str:
    return os.environ.get("COTW_MONITOR_STATE_BRANCH") or DEFAULT_BRANCH


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class State:
    filed: dict = field(default_factory=dict)
    decided: dict = field(default_factory=dict)
    summary: dict | None = None
    names: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    # where it was read from: the branch exists / the file's blob sha (None: not created yet)
    branch_exists: bool = False
    sha: str | None = None

    def known(self) -> set[str]:
        return set(self.filed) | set(self.decided)

    def to_json(self) -> dict:
        return {
            "version": VERSION, "filed": dict(sorted(self.filed.items())), "decided": dict(sorted(self.decided.items())), "summary": self.summary,
            "names": {q: dict(sorted(parts.items())) for q, parts in sorted(self.names.items(), key=lambda kv: (len(kv[0]), kv[0]))},
            "sources": dict(sorted(self.sources.items())),
        }

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"

    def decide(self, fp: str, source: str, when: str | None = None) -> None:
        self.filed.pop(fp, None)
        self.decided[fp] = {"source": source, "decided_at": when or now_iso()}


def parse(text: str) -> State:
    data = json.loads(text)
    if data.get("version") not in READABLE:
        raise RuntimeError(f"{STATE_FILE}: unsupported version {data.get('version')!r}")
    return State(
        filed=dict(data.get("filed") or {}), decided=dict(data.get("decided") or {}), summary=data.get("summary"),
        names=dict(data.get("names") or {}), sources=dict(data.get("sources") or {}),
    )


def load(client, branch: str | None = None) -> State:
    """The state on ``branch``; an empty one if the branch or the file does not exist yet."""
    branch = branch or state_branch()
    if client.branch(branch) is None:
        return State()
    meta = client.file(STATE_FILE, branch)
    if meta is None:
        return State(branch_exists=True)
    state = parse(base64.b64decode(meta["content"]).decode("utf-8"))
    state.branch_exists, state.sha = True, meta["sha"]
    return state


def save(client, state: State, message: str, branch: str | None = None) -> None:
    """One commit on ``branch``: create the branch from the default branch if needed, then
    create or update the file (the stored sha guards against a concurrent writer)."""
    branch = branch or state_branch()
    if not state.branch_exists:
        default = client.repository().get("default_branch") or "main"
        client.create_branch(branch, default)
        state.branch_exists = True
    content = base64.b64encode(state.dumps().encode("utf-8")).decode("ascii")
    result = client.write_file(STATE_FILE, branch, content, message, state.sha)
    state.sha = ((result or {}).get("content") or {}).get("sha", state.sha)


class FileStore:
    """A local stand-in for the state branch (``check-wikidata --dry-run --state-file PATH``):
    the state file is read from and written to ``path``, nothing else is touched."""

    def __init__(self, path):
        from pathlib import Path

        self.path = Path(path)

    def repository(self) -> dict:
        return {"default_branch": "main"}

    def branch(self, name: str) -> dict:
        return {"name": name}

    def file(self, path: str, ref: str) -> dict | None:
        if not self.path.exists():
            return None
        raw = self.path.read_bytes()
        return {"content": base64.b64encode(raw).decode("ascii"), "sha": hashlib.sha1(raw).hexdigest()}

    def write_file(self, path: str, branch: str, content_b64: str, message: str, sha: str | None = None) -> dict:
        raw = base64.b64decode(content_b64)
        self.path.write_bytes(raw)
        return {"content": {"sha": hashlib.sha1(raw).hexdigest()}}
