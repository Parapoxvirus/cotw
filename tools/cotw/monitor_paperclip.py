"""Paperclip task sink of the change monitor (docs/MONITORING.md, *Paperclip sink*).

Selected when ``PAPERCLIP_API_URL``, ``PAPERCLIP_API_KEY``, ``PAPERCLIP_COMPANY_ID`` and
``PAPERCLIP_PROJECT_ID`` are all set; otherwise the monitor files Gitea issues. The key is a
restricted task bridge key: it creates tasks in one project and reads the tasks it created, but
can neither list, update nor comment on them. Dedupe therefore lives in the state file of
``monitor_state`` instead of the tasks themselves.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import monitor_state
from .monitor import FINGERPRINT_RE, Deviation, order, render_issue, render_summary

# A task in one of these states is decided: its fingerprint is never filed again.
TERMINAL = {"done", "cancelled", "canceled", "closed", "archived", "rejected", "wont_do"}
ENV = ("PAPERCLIP_API_URL", "PAPERCLIP_API_KEY", "PAPERCLIP_COMPANY_ID", "PAPERCLIP_PROJECT_ID")


class PaperclipError(RuntimeError):
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


@dataclass
class Config:
    url: str  # API base, ends with /api
    key: str
    company: str
    project: str
    assignee: str | None = None


def config() -> Config | None:
    """The Paperclip sink's settings from the environment; ``None`` (Gitea issues) unless all
    four required variables are set. Empty values count as unset (unset CI variables)."""
    values = [os.environ.get(name) or None for name in ENV]
    if not all(values):
        return None
    url, key, company, project = values
    return Config(url.rstrip("/"), key, company, project, os.environ.get("PAPERCLIP_ASSIGNEE_AGENT_ID") or None)


class Paperclip:
    """The two Paperclip API calls the monitor needs. The key is sent, never printed."""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _req(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.cfg.url + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.cfg.key}", "Content-Type": "application/json", "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            raise PaperclipError(f"Paperclip {method} {path}: HTTP {exc.code} {exc.read().decode('utf-8', 'replace')[:300]}", exc.code) from None

    def create_task(self, title: str, description: str) -> dict:
        body = {"title": title, "description": description, "projectId": self.cfg.project, "status": "todo"}
        if self.cfg.assignee:
            body["assigneeAgentId"] = self.cfg.assignee
        return self._req("POST", f"/companies/{self.cfg.company}/issues", body)

    def task(self, task_id: str) -> dict:
        return self._req("GET", f"/issues/{task_id}")


def _status(client, task_id: str, label: str, log) -> str | None:
    """The task's status; ``"gone"`` if it was deleted, ``None`` if it could not be read (the
    task stays filed and is asked again next run)."""
    try:
        return str(client.task(task_id).get("status") or "").lower() or None
    except PaperclipError as exc:
        if exc.code == 404:
            return "gone"
        log(f"warning: status of {label} not readable, kept as filed: {exc}")
        return None


def refresh(state: monitor_state.State, client, log=print) -> int:
    """Move every filed task that reached a terminal status (or was deleted) to ``decided``;
    forget a terminal summary task. Returns the number of newly decided fingerprints."""
    decided = 0
    for fp, rec in list(state.filed.items()):
        label = rec.get("identifier") or rec.get("task_id")
        status = _status(client, rec["task_id"], label, log)
        if status in TERMINAL or status == "gone":
            state.decide(fp, f"paperclip-{status}:{label}")
            log(f"decided ({status}): {label} {rec.get('title', '')}")
            decided += 1
    if state.summary:
        label = state.summary.get("identifier") or state.summary.get("task_id")
        status = _status(client, state.summary["task_id"], label, log)
        if status in TERMINAL or status == "gone":
            log(f"summary {label} is {status}")
            state.summary = None
    return decided


def summary_text(overflow: list[Deviation], cap: int) -> tuple[str, str]:
    title, body = render_summary(overflow, cap)
    body = body.replace(
        "each later run files the next batch (and updates this issue).",
        "each later run files the next batch. This task is never updated: close it, and the next run files a fresh summary if deviations are still waiting.",
    )
    return title, body


def file_tasks(devs: list[Deviation], client, store, max_issues: int, log=print, dry_run: bool = False) -> dict:
    """Paperclip counterpart of ``monitor.file_issues``. ``store`` is the Gitea client holding
    the state branch. The state is written once at the end, also when creating a task failed
    halfway, so a created task is never filed twice."""
    state = monitor_state.load(store)
    decided = refresh(state, client, log)
    known = state.known()
    fresh = [d for d in order(devs) if d.fingerprint not in known]
    filed, overflow = fresh[:max_issues], fresh[max_issues:]
    result = {"known": len(devs) - len(fresh), "filed": 0, "overflow": len(overflow), "decided": decided}
    if dry_run:
        for i, d in enumerate(fresh):
            log(f"[{'would file' if i < max_issues else 'summary'}] {d.fingerprint} {d.title}: {d.old_text} -> {d.new_text}")
        for d in devs:
            if d.fingerprint in known:
                log(f"[filed already] {d.fingerprint} {d.title}")
        summary = "no summary" if not overflow else ("1 summary" if state.summary is None else f"summary {state.summary.get('identifier')} still open")
        log(f"dry run: {len(filed)} tasks + {summary} would be written, nothing touched")
        return result
    changed = decided > 0
    try:
        for d in filed:
            title, body = render_issue(d)
            task = client.create_task(title, body)
            state.filed[d.fingerprint] = {
                "task_id": task["id"], "identifier": task.get("identifier"), "title": title, "filed_at": monitor_state.now_iso(),
            }
            changed = True
            result["filed"] += 1
            log(f"filed {task.get('identifier') or task['id']}: {title}")
        if overflow and state.summary is None:
            title, body = summary_text(overflow, max_issues)
            task = client.create_task(title, body)
            state.summary = {"task_id": task["id"], "identifier": task.get("identifier")}
            changed = True
            log(f"filed summary {task.get('identifier') or task['id']}: {len(overflow)} waiting")
        elif overflow:
            log(f"summary {state.summary.get('identifier')} still open (tasks cannot be updated): {len(overflow)} waiting")
        elif state.summary:
            log(f"nothing waiting: summary {state.summary.get('identifier')} can be closed")
    finally:
        if changed:
            monitor_state.save(store, state, f"cotw-monitor: {result['filed']} filed, {decided} decided")
            log(f"state saved to {monitor_state.state_branch()}:{monitor_state.STATE_FILE}")
    return result


def import_issues(store, apply: bool, log=print) -> int:
    """Seed ``decided`` from the Gitea issues the monitor filed before the Paperclip sink: closed
    ones were decided, open ones were migrated by hand. Idempotent; dry run unless ``apply``."""
    state = monitor_state.load(store)
    added = 0
    for issue in sorted(store.issues(), key=lambda i: i["number"]):
        for fp in FINGERPRINT_RE.findall(issue.get("body") or ""):
            if fp in state.decided or fp in state.filed:
                continue
            closed = issue.get("state") == "closed"
            source = f"gitea-{'closed' if closed else 'open'}:{issue['number']}"
            when = issue.get("closed_at") if closed and issue.get("closed_at") else None
            state.decided[fp] = {"source": source, "decided_at": when or monitor_state.now_iso()}
            added += 1
            log(f"{'import' if apply else 'would import'} {fp} ({source}) {issue.get('title', '')}")
    log(f"{added} fingerprints new, {len(state.decided)} decided in total")
    if apply and added:
        monitor_state.save(store, state, f"cotw-monitor: import {added} fingerprints from Gitea issues")
        log(f"state saved to {monitor_state.state_branch()}:{monitor_state.STATE_FILE}")
    elif not apply:
        log("dry run: nothing written (--apply writes the state)")
    return 0


def check(cfg: Config, dry_run: bool, max_issues: int, url: str | None, repo: str | None, token: str | None, collect, gitea_cls, log=print) -> int:
    """``check-wikidata`` with the Paperclip sink. Without the Gitea repository and token the
    state cannot be kept, so the run is a dry run that treats every deviation as new."""
    if not dry_run and not (url and repo and token):
        log("Paperclip sink without Gitea URL/repository/COTW_MONITOR_TOKEN for the state branch: dry run")
        dry_run = True
    devs, report = collect(log=log)
    log(f"{len(devs)} deviations ({report['rejected']} rejected via overrides, {report['damped']} damped)")
    log(f"sink: Paperclip project tasks, state on {monitor_state.state_branch()}:{monitor_state.STATE_FILE}")
    client = Paperclip(cfg)
    if not (url and repo and token):
        for i, d in enumerate(order(devs)):
            log(f"[{'would file' if i < max_issues else 'summary'}] {d.fingerprint} {d.title}: {d.old_text} -> {d.new_text}")
        log("dry run without state: nothing touched")
        return 0
    store = gitea_cls(url, repo, token)
    result = file_tasks(devs, client, store, max_issues, log, dry_run=dry_run)
    if not dry_run:
        log(f"{result['filed']} filed, {result['known']} filed or decided before, {result['decided']} newly decided, {result['overflow']} in the summary")
    return 0
