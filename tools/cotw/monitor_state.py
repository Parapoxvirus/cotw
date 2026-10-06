"""Dedupe state of the Paperclip sink of the change monitor (docs/MONITORING.md).

Gitea issues carry their own state: the fingerprint marker in the body, open or closed. A
Paperclip task bridge key can create tasks and read the ones it created, but cannot list them,
so the monitor keeps what it filed in one JSON file on a dedicated branch of the repository,
read and written through the Gitea contents API:

```json
{"version": 1,
 "filed":   {"<fingerprint>": {"task_id", "identifier", "title", "filed_at"}},
 "decided": {"<fingerprint>": {"source", "decided_at"}},
 "summary": {"task_id", "identifier"} | null}
```

``filed`` tasks are still being worked on; ``decided`` fingerprints are never filed again (a
closed or cancelled task, like a closed issue).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_BRANCH = "cotw-monitor-state"
STATE_FILE = "cotw-monitor-state.json"
VERSION = 1


def state_branch() -> str:
    return os.environ.get("COTW_MONITOR_STATE_BRANCH") or DEFAULT_BRANCH


def now_iso(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class State:
    filed: dict = field(default_factory=dict)
    decided: dict = field(default_factory=dict)
    summary: dict | None = None
    # where it was read from: the branch exists / the file's blob sha (None: not created yet)
    branch_exists: bool = False
    sha: str | None = None

    def known(self) -> set[str]:
        return set(self.filed) | set(self.decided)

    def to_json(self) -> dict:
        return {"version": VERSION, "filed": dict(sorted(self.filed.items())), "decided": dict(sorted(self.decided.items())), "summary": self.summary}

    def dumps(self) -> str:
        return json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n"

    def decide(self, fp: str, source: str, when: str | None = None) -> None:
        self.filed.pop(fp, None)
        self.decided[fp] = {"source": source, "decided_at": when or now_iso()}


def parse(text: str) -> State:
    data = json.loads(text)
    if data.get("version") != VERSION:
        raise RuntimeError(f"{STATE_FILE}: unsupported version {data.get('version')!r}")
    return State(filed=dict(data.get("filed") or {}), decided=dict(data.get("decided") or {}), summary=data.get("summary"))


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
