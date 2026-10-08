"""Paperclip sink of the change monitor: sink selection, the state file on its branch, terminal
tasks → decided, flood cap, the one-time import. Offline: HTTP is mocked, nothing leaves the
process."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import urllib.error

import pytest
import yaml

from cotw import monitor, monitor_paperclip, monitor_state, paths
from cotw.monitor import Deviation

QUIET = dict(log=lambda *_: None)
PAPERCLIP_ENV = {
    "PAPERCLIP_API_URL": "https://paperclip.example.com/api",
    "PAPERCLIP_API_KEY": "placeholder-key",
    "PAPERCLIP_COMPANY_ID": "company-0000",
    "PAPERCLIP_PROJECT_ID": "project-0000",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (*PAPERCLIP_ENV, "PAPERCLIP_ASSIGNEE_AGENT_ID", "COTW_MONITOR_STATE_BRANCH", "COTW_MONITOR_TOKEN", "COTW_MONITOR_NOTIFY_ISSUE"):
        monkeypatch.delenv(name, raising=False)


def _devs(n, alert_at=None):
    return [
        Deviation(f"{i:03d}", "iso3", "OLD", f"N{i:02d}", "iso3", f"Q{i + 1}", "P298", [f"{i:03d}"],
                  title=f"Größere Änderung {i}", alert=(i == alert_at))
        for i in range(n)
    ]


class FakeStore:
    """Gitea with a contents API in memory: branches, one file per (branch, path), issues."""

    def __init__(self, issues=(), branches=("main",)):
        self.branches = {b: {} for b in branches}
        self._issues = [dict(i) for i in issues]
        self.writes: list[tuple] = []

    def repository(self):
        return {"default_branch": "main", "permissions": {"push": True}}

    def issues(self):
        return [dict(i) for i in self._issues]

    def branch(self, name):
        return {"name": name} if name in self.branches else None

    def create_branch(self, name, source):
        assert name not in self.branches
        self.branches[name] = dict(self.branches[source])
        self.writes.append(("branch", name, source))

    def file(self, path, ref):
        files = self.branches[ref]
        if path not in files:
            return None
        content, sha = files[path]
        return {"content": content, "sha": sha}

    def write_file(self, path, branch, content_b64, message, sha=None):
        files = self.branches[branch]
        if sha is None:
            assert path not in files, "create over an existing file"
        else:
            assert files[path][1] == sha, "stale sha"
        new_sha = hashlib.sha1(content_b64.encode()).hexdigest()
        files[path] = (content_b64, new_sha)
        self.writes.append(("put" if sha else "post", path, branch, message))
        return {"content": {"sha": new_sha}}

    def state(self, branch="cotw-monitor-state"):
        content, _ = self.branches[branch][monitor_state.STATE_FILE]
        return json.loads(base64.b64decode(content))


class FakePaperclip:
    def __init__(self, fail_after=None):
        self.tasks: dict[str, dict] = {}
        self.fail_after = fail_after
        self.created: list[dict] = []

    def create_task(self, title, description):
        if self.fail_after is not None and len(self.created) >= self.fail_after:
            raise monitor_paperclip.PaperclipError("Paperclip POST: HTTP 500", 500)
        n = len(self.tasks) + 1
        task = {"id": f"task-{n:04d}", "identifier": f"COTW-{n}", "status": "todo", "title": title, "description": description}
        self.tasks[task["id"]] = task
        self.created.append(task)
        return dict(task)

    def task(self, task_id):
        if task_id not in self.tasks:
            raise monitor_paperclip.PaperclipError("Paperclip GET: HTTP 404", 404)
        return dict(self.tasks[task_id])


# --- sink selection -----------------------------------------------------------------------------


def test_sink_needs_all_four_variables(monkeypatch):
    assert monitor_paperclip.config() is None
    for name, value in PAPERCLIP_ENV.items():
        monkeypatch.setenv(name, value)
    cfg = monitor_paperclip.config()
    assert cfg.company == "company-0000" and cfg.assignee is None
    monkeypatch.setenv("PAPERCLIP_PROJECT_ID", "")  # an unset CI variable arrives as ""
    assert monitor_paperclip.config() is None


def test_check_dispatches_to_paperclip_only_when_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(monitor, "collect", lambda log=print: (_devs(1), {"rejected": 0, "damped": 0}))
    monkeypatch.setattr(monitor_paperclip, "check", lambda *a, **k: calls.append("paperclip") or 0)
    monkeypatch.setattr(monitor, "file_issues", lambda *a, **k: calls.append("gitea") or {"filed": 0, "known": 0, "overflow": 0})
    monkeypatch.setattr(monitor, "Gitea", lambda *a: _GiteaStub())
    monkeypatch.setenv("COTW_MONITOR_TOKEN", "placeholder")
    assert monitor.check(False, 20, "https://gitea.example.com", "owner/cotw", **QUIET) == 0
    assert calls == ["gitea"]  # default: Gitea issues, unchanged
    for name, value in PAPERCLIP_ENV.items():
        monkeypatch.setenv(name, value)
    assert monitor.check(False, 20, "https://gitea.example.com", "owner/cotw", **QUIET) == 0
    assert calls == ["gitea", "paperclip"]


class _GiteaStub:
    def repository(self):
        return {"permissions": {}}

    def issues(self):
        return []


def test_paperclip_without_gitea_token_is_a_dry_run(monkeypatch):
    for name, value in PAPERCLIP_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(monitor, "collect", lambda log=print: (_devs(3), {"rejected": 0, "damped": 0}))

    def no_network(*_a, **_k):
        raise AssertionError("no writes without the state branch")

    monkeypatch.setattr(monitor_paperclip.Paperclip, "create_task", no_network)
    monkeypatch.setattr(monitor, "Gitea", no_network)
    lines = []
    assert monitor.check(False, 2, "https://gitea.example.com", "owner/cotw", log=lines.append) == 0
    assert any("dry run" in line for line in lines)
    assert sum("[would file]" in line for line in lines) == 2


# --- state file ---------------------------------------------------------------------------------


def test_state_roundtrip_creates_branch_then_updates_with_sha():
    store = FakeStore()
    state = monitor_state.load(store)
    assert state.known() == set() and not state.branch_exists
    state.filed["0123456789abcdef"] = {"task_id": "task-1", "identifier": "COTW-1", "title": "Jürgen Groß", "filed_at": "2026-10-05T04:17:00Z"}
    monitor_state.save(store, state, "first")
    assert store.writes[0] == ("branch", "cotw-monitor-state", "main")
    assert store.writes[1][0] == "post"
    raw = base64.b64decode(store.branches["cotw-monitor-state"][monitor_state.STATE_FILE][0]).decode("utf-8")
    assert "Jürgen Groß" in raw  # UTF-8, not \u escapes
    again = monitor_state.load(store)
    assert again.filed == state.filed and again.sha and again.branch_exists
    again.decide("0123456789abcdef", "paperclip-done:COTW-1", "2026-10-12T04:17:00Z")
    monitor_state.save(store, again, "second")
    assert store.writes[2][0] == "put" and len(store.writes) == 3
    data = store.state()
    assert data == {
        "version": 2, "filed": {}, "summary": None, "names": {}, "sources": {},
        "decided": {"0123456789abcdef": {"source": "paperclip-done:COTW-1", "decided_at": "2026-10-12T04:17:00Z"}},
    }


def test_state_branch_from_env(monkeypatch):
    monkeypatch.setenv("COTW_MONITOR_STATE_BRANCH", "monitor-state-test")
    store = FakeStore()
    monitor_state.save(store, monitor_state.State(), "init")
    assert "monitor-state-test" in store.branches


def test_state_rejects_unknown_version():
    with pytest.raises(RuntimeError):
        monitor_state.parse('{"version": 3}')


def test_state_v1_migrates_to_v2():
    v1 = {"version": 1, "filed": {}, "summary": None, "decided": {"0123456789abcdef": {"source": "x", "decided_at": "y"}}}
    state = monitor_state.parse(json.dumps(v1))
    assert state.names == {} and state.sources == {} and state.known() == {"0123456789abcdef"}
    assert state.to_json()["version"] == 2


# --- filing -------------------------------------------------------------------------------------


def test_new_deviations_are_filed_and_state_is_written():
    store, pc = FakeStore(), FakePaperclip()
    result = monitor_paperclip.file_tasks(_devs(3), pc, store, 20, **QUIET)
    assert result == {"known": 0, "filed": 3, "overflow": 0, "decided": 0}
    task = pc.created[0]
    assert f"<!-- cotw-monitor fingerprint={_devs(3)[0].fingerprint} -->" in task["description"]
    assert set(store.state()["filed"]) == {d.fingerprint for d in _devs(3)}
    assert store.state()["filed"][_devs(3)[0].fingerprint]["identifier"] == "COTW-1"
    # second run: everything known, no task, no state commit
    n_writes = len(store.writes)
    assert monitor_paperclip.file_tasks(_devs(3), pc, store, 20, **QUIET)["filed"] == 0
    assert len(pc.created) == 3 and len(store.writes) == n_writes


def test_terminal_tasks_move_to_decided_and_are_never_refiled():
    store, pc = FakeStore(), FakePaperclip()
    devs = _devs(3)
    monitor_paperclip.file_tasks(devs, pc, store, 20, **QUIET)
    pc.tasks["task-0001"]["status"] = "done"
    pc.tasks["task-0002"]["status"] = "cancelled"
    pc.tasks["task-0003"]["status"] = "in_progress"
    result = monitor_paperclip.file_tasks(devs, pc, store, 20, **QUIET)
    assert result["decided"] == 2 and result["filed"] == 0
    state = store.state()
    assert set(state["decided"]) == {devs[0].fingerprint, devs[1].fingerprint}
    assert state["decided"][devs[0].fingerprint]["source"] == "paperclip-done:COTW-1"
    assert set(state["filed"]) == {devs[2].fingerprint}
    assert len(pc.created) == 3


def test_deleted_task_is_decided_unreadable_task_stays_filed():
    store, pc = FakeStore(), FakePaperclip()
    devs = _devs(2)
    monitor_paperclip.file_tasks(devs, pc, store, 20, **QUIET)
    del pc.tasks["task-0001"]
    real_task = pc.task

    def flaky(task_id):
        if task_id == "task-0002":
            raise monitor_paperclip.PaperclipError("HTTP 502", 502)
        return real_task(task_id)

    pc.task = flaky
    lines = []
    monitor_paperclip.file_tasks(devs, pc, store, 20, log=lines.append)
    state = store.state()
    assert state["decided"][devs[0].fingerprint]["source"].startswith("paperclip-gone:")
    assert devs[1].fingerprint in state["filed"] and len(pc.created) == 2
    assert any("warning" in line for line in lines)


def test_assignee_and_payload(monkeypatch):
    sent = []

    def fake_urlopen(req, timeout):
        sent.append((req.get_method(), req.full_url, dict(req.header_items()), json.loads(req.data) if req.data else None))
        return io.BytesIO(json.dumps({"id": "task-1", "identifier": "COTW-1", "status": "todo"}).encode())

    monkeypatch.setattr(monitor_paperclip.urllib.request, "urlopen", fake_urlopen)
    for name, value in PAPERCLIP_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PAPERCLIP_ASSIGNEE_AGENT_ID", "agent-0000")
    client = monitor_paperclip.Paperclip(monitor_paperclip.config())
    client.create_task("Größe", "body")
    client.task("task-1")
    method, url, headers, body = sent[0]
    assert (method, url) == ("POST", "https://paperclip.example.com/api/companies/company-0000/issues")
    assert headers["Authorization"] == "Bearer placeholder-key"
    assert body == {"title": "Größe", "description": "body", "projectId": "project-0000", "status": "todo", "assigneeAgentId": "agent-0000"}
    assert sent[1][:2] == ("GET", "https://paperclip.example.com/api/issues/task-1")


def test_cap_overflow_summary_only_when_none_open():
    store, pc = FakeStore(), FakePaperclip()
    devs = _devs(5, alert_at=4)
    result = monitor_paperclip.file_tasks(devs, pc, store, 2, **QUIET)
    assert result == {"known": 0, "filed": 2, "overflow": 3, "decided": 0}
    assert pc.created[0]["title"] == "Größere Änderung 4"  # the non-free alert jumps the queue
    summary = pc.created[2]
    assert monitor.SUMMARY_MARKER in summary["description"] and "3 more" in summary["title"]
    assert "never updated" in summary["description"]
    assert store.state()["summary"] == {"task_id": summary["id"], "identifier": summary["identifier"]}
    # next run: 2 more filed, the open summary is not duplicated (it cannot be updated)
    monitor_paperclip.file_tasks(devs, pc, store, 2, **QUIET)
    assert len(pc.created) == 5 and sum(monitor.SUMMARY_MARKER in t["description"] for t in pc.created) == 1
    # the summary is closed by hand; the remaining deviation gets a fresh summary
    pc.tasks[summary["id"]]["status"] = "done"
    monitor_paperclip.file_tasks(_devs(6, alert_at=4), pc, store, 0, **QUIET)
    summaries = [t for t in pc.created if monitor.SUMMARY_MARKER in t["description"]]
    assert len(summaries) == 2 and store.state()["summary"]["task_id"] == summaries[1]["id"]


def test_state_is_written_when_a_create_fails_halfway():
    store, pc = FakeStore(), FakePaperclip(fail_after=2)
    with pytest.raises(monitor_paperclip.PaperclipError):
        monitor_paperclip.file_tasks(_devs(4), pc, store, 20, **QUIET)
    assert len(store.state()["filed"]) == 2  # the two created tasks are remembered
    pc.fail_after = None
    monitor_paperclip.file_tasks(_devs(4), pc, store, 20, **QUIET)
    assert len(pc.created) == 4  # no duplicates


def test_dry_run_reads_but_never_writes():
    store, pc = FakeStore(), FakePaperclip()
    lines = []
    result = monitor_paperclip.file_tasks(_devs(3), pc, store, 2, log=lines.append, dry_run=True)
    assert result["filed"] == 0 and pc.created == [] and store.writes == []
    assert sum("[would file]" in line for line in lines) == 2 and sum("[summary]" in line for line in lines) == 1


def test_rejected_and_known_counts_through_check(monkeypatch):
    for name, value in PAPERCLIP_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("COTW_MONITOR_TOKEN", "placeholder")
    store, pc = FakeStore(), FakePaperclip()
    monkeypatch.setattr(monitor, "collect", lambda log=print: (_devs(2), {"rejected": 0, "damped": 0}))
    monkeypatch.setattr(monitor, "Gitea", lambda *a: store)
    monkeypatch.setattr(monitor_paperclip, "Paperclip", lambda cfg: pc)
    assert monitor.check(False, 20, "https://gitea.example.com", "owner/cotw", **QUIET) == 0
    assert len(pc.created) == 2 and len(store.state()["filed"]) == 2


# --- import -------------------------------------------------------------------------------------


def test_import_seeds_decided_from_open_and_closed_issues():
    devs = _devs(3)
    bodies = [monitor.render_issue(d)[1] for d in devs]
    issues = [
        {"number": 7, "title": "a", "body": bodies[0], "state": "closed", "closed_at": "2026-09-30T10:00:00Z"},
        {"number": 8, "title": "b", "body": bodies[1], "state": "open"},
        {"number": 9, "title": "summary", "body": monitor.render_summary(devs[2:], 2)[1], "state": "open"},
    ]
    store = FakeStore(issues)
    monitor_paperclip.import_issues(store, apply=False, **QUIET)
    assert store.writes == []  # dry run by default
    monitor_paperclip.import_issues(store, apply=True, **QUIET)
    decided = store.state()["decided"]
    assert decided[devs[0].fingerprint] == {"source": "gitea-closed:7", "decided_at": "2026-09-30T10:00:00Z"}
    assert decided[devs[1].fingerprint]["source"] == "gitea-open:8"
    assert devs[2].fingerprint not in decided  # only listed in the summary, never filed
    # idempotent: a second import writes nothing
    n = len(store.writes)
    monitor_paperclip.import_issues(store, apply=True, **QUIET)
    assert len(store.writes) == n
    # and the sink files only the deviation that never had an issue
    pc = FakePaperclip()
    monitor_paperclip.file_tasks(devs, pc, store, 20, **QUIET)
    assert [t["title"] for t in pc.created] == [devs[2].title]


def test_import_cli_needs_token(monkeypatch):
    lines = []
    assert monitor.import_issues(True, "https://gitea.example.com", "owner/cotw", log=lines.append) == 1


# --- Gitea contents API (HTTP mocked) ------------------------------------------------------------


def test_gitea_contents_calls(monkeypatch):
    sent = []
    responses = {
        ("GET", "/branches/cotw-monitor-state"): urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b"{}")),
        ("GET", "/contents/cotw-monitor-state.json"): urllib.error.HTTPError("u", 404, "nf", {}, io.BytesIO(b"{}")),
        ("GET", ""): {"default_branch": "main"},
        ("POST", "/branches"): {"name": "cotw-monitor-state"},
        ("POST", "/contents/cotw-monitor-state.json"): {"content": {"sha": "f" * 40}},
        ("PUT", "/contents/cotw-monitor-state.json"): {"content": {"sha": "e" * 40}},
    }

    def fake_urlopen(req, timeout):
        prefix = "https://gitea.example.com/api/v1/repos/owner/cotw"
        path = req.full_url.removeprefix(prefix).split("?")[0]
        sent.append((req.get_method(), path, req.full_url, json.loads(req.data) if req.data else None, req.get_header("Authorization")))
        resp = responses[(req.get_method(), path)]
        if isinstance(resp, Exception):
            raise resp
        return io.BytesIO(json.dumps(resp).encode())

    monkeypatch.setattr(monitor.urllib.request, "urlopen", fake_urlopen)
    client = monitor.Gitea("https://gitea.example.com", "owner/cotw", "placeholder")
    state = monitor_state.load(client)
    assert not state.branch_exists
    state.decide("0123456789abcdef", "gitea-closed:1", "2026-10-05T00:00:00Z")
    monitor_state.save(client, state, "seed")
    monitor_state.save(client, state, "again")
    methods = [(m, p) for m, p, *_ in sent]
    assert methods == [
        ("GET", "/branches/cotw-monitor-state"), ("GET", ""), ("POST", "/branches"),
        ("POST", "/contents/cotw-monitor-state.json"), ("PUT", "/contents/cotw-monitor-state.json"),
    ]
    assert sent[2][3] == {"new_branch_name": "cotw-monitor-state", "old_branch_name": "main"}
    post, put = sent[3][3], sent[4][3]
    assert post["branch"] == "cotw-monitor-state" and "sha" not in post
    assert put["sha"] == "f" * 40
    assert json.loads(base64.b64decode(post["content"]))["decided"]["0123456789abcdef"]["source"] == "gitea-closed:1"
    assert all(auth == "token placeholder" for *_, auth in sent)


def test_gitea_reads_existing_state_file(monkeypatch):
    payload = monitor_state.State(decided={"0123456789abcdef": {"source": "x", "decided_at": "y"}}).dumps()

    def fake_urlopen(req, timeout):
        if "/contents/" in req.full_url:
            assert req.full_url.endswith("?ref=cotw-monitor-state")
            return io.BytesIO(json.dumps({"content": base64.encodebytes(payload.encode()).decode(), "sha": "d" * 40}).encode())
        return io.BytesIO(b'{"name": "cotw-monitor-state"}')

    monkeypatch.setattr(monitor.urllib.request, "urlopen", fake_urlopen)
    state = monitor_state.load(monitor.Gitea("https://gitea.example.com", "owner/cotw", "placeholder"))
    assert state.sha == "d" * 40 and state.known() == {"0123456789abcdef"}


def test_workflow_passes_paperclip_settings():
    wf = yaml.safe_load((paths.ROOT / ".gitea" / "workflows" / "wikidata-check.yml").read_text(encoding="utf-8"))
    assert wf["permissions"] == {"contents": "write", "issues": "write"}
    env = next(s for s in next(iter(wf["jobs"].values()))["steps"] if "env" in s)["env"]
    assert env["PAPERCLIP_API_KEY"] == "${{ secrets.PAPERCLIP_TASK_KEY }}"
    for name in ("PAPERCLIP_API_URL", "PAPERCLIP_COMPANY_ID", "PAPERCLIP_PROJECT_ID", "PAPERCLIP_ASSIGNEE_AGENT_ID", "COTW_MONITOR_NOTIFY_ISSUE"):
        assert env[name] == "${{ vars.%s }}" % name
    assert "github.token" in env["COTW_MONITOR_TOKEN"]
