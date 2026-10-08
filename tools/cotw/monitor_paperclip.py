"""Paperclip task sink of the change monitor (docs/MONITORING.md, *Paperclip sink*).

Selected when ``PAPERCLIP_API_URL``, ``PAPERCLIP_API_KEY``, ``PAPERCLIP_COMPANY_ID`` and
``PAPERCLIP_PROJECT_ID`` are all set; otherwise the monitor files Gitea issues. The key is a
restricted task bridge key: it creates tasks in one project and reads the tasks it created, but
can neither list, update nor comment on them. Dedupe therefore lives in the state file of
``monitor_state`` instead of the tasks themselves, and so do the baselines of the name and
naming-source checks (``monitor_watch``).

Because the key cannot comment either, a run that files tasks also files one **digest task**
when ``COTW_MONITOR_NOTIFY_ISSUE`` is set: it lists the new tasks and asks its assignee to post
that list as one comment on the notify issue.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from . import monitor_state, monitor_watch
from .monitor import CHECK_STEPS, FINGERPRINT_RE, Deviation, order, render_issue, render_summary

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
    notify: str | None = None  # issue the digest asks to comment on (COTW_MONITOR_NOTIFY_ISSUE)


def config() -> Config | None:
    """The Paperclip sink's settings from the environment; ``None`` (Gitea issues) unless all
    four required variables are set. Empty values count as unset (unset CI variables)."""
    values = [os.environ.get(name) or None for name in ENV]
    if not all(values):
        return None
    url, key, company, project = values
    return Config(
        url.rstrip("/"), key, company, project, os.environ.get("PAPERCLIP_ASSIGNEE_AGENT_ID") or None,
        os.environ.get("COTW_MONITOR_NOTIFY_ISSUE") or None,
    )


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


def digest_text(created: list[tuple[str, str]], overflow: int, notify: str, today: str) -> tuple[str, str]:
    """The digest task: one line per task filed in this run, and what to do with them."""
    findings = [c for c in created if not c[1].startswith("Wikidata check:")]
    n = len(findings)
    title = f"cotw monitor: {n} new finding{'' if n == 1 else 's'} ({today})"
    summary = [f"cotw monitor {today}: {n} new finding{'' if n == 1 else 's'}"] + [f"- {ident}: {title_}" for ident, title_ in created]
    if overflow:
        summary.append(f"- {overflow} more waiting (flood cap), filed by later runs")
    lines = [
        f"Post the summary below as **one comment on {notify}**, unchanged, then mark this task done. Do not work on the listed tasks here.",
        "",
        "---",
        "",
        *summary,
    ]
    return title, "\n".join(lines)


def _dry_details(d: Deviation, log) -> None:
    if d.kind in CHECK_STEPS:
        for line in d.changes:
            log(f"    {line}")
        if d.reminder:
            log(f"    {d.reminder}")


def file_tasks(devs: list[Deviation], client, store, max_issues: int, log=print, dry_run: bool = False,
               watch=None, notify: str | None = None, local: bool = False) -> dict:
    """Paperclip counterpart of ``monitor.file_issues``. ``store`` is the Gitea client holding
    the state branch (or a ``monitor_state.FileStore``). The state is written once at the end,
    also when creating a task failed halfway, so a created task is never filed twice.

    ``watch(state, log)`` runs the name and naming-source checks (``monitor_watch.run``) against
    the baselines in the state; their findings join ``devs`` and the baseline moves for what is
    filed. ``notify``: file one digest task listing the new tasks. ``local``: a dry run against
    a local state file that still writes the seeded baseline to it."""
    state = monitor_state.load(store)
    decided = refresh(state, client, log) if client is not None else 0
    watched = watch(state, log) if watch else None  # network reads, before the first write
    if watched:
        devs = devs + watched.devs
    baseline = json.dumps([state.names, state.sources], sort_keys=True)
    known = state.known()
    fresh = [d for d in order(devs) if d.fingerprint not in known]
    filed, overflow = fresh[:max_issues], fresh[max_issues:]
    result = {"known": len(devs) - len(fresh), "filed": 0, "overflow": len(overflow), "decided": decided}
    if dry_run:
        for i, d in enumerate(fresh):
            log(f"[{'would file' if i < max_issues else 'summary'}] {d.fingerprint} {d.title}: {d.old_text} -> {d.new_text}")
            _dry_details(d, log)
        for d in devs:
            if d.fingerprint in known:
                log(f"[filed already] {d.fingerprint} {d.title}")
        summary = "no summary" if not overflow else ("1 summary" if state.summary is None else f"summary {state.summary.get('identifier')} still open")
        if local and watched:
            monitor_watch.advance(state, watched, set(), dry_run=True)
            if json.dumps([state.names, state.sources], sort_keys=True) != baseline:
                monitor_state.save(store, state, "cotw-monitor: local baseline")
                log(f"dry run: {len(filed)} tasks + {summary} would be written; seeded baseline written to {store.path}")
                return result
        log(f"dry run: {len(filed)} tasks + {summary} would be written, nothing touched")
        return result
    changed = decided > 0
    created: list[tuple[str, str]] = []
    try:
        for d in filed:
            title, body = render_issue(d)
            task = client.create_task(title, body)
            state.filed[d.fingerprint] = {
                "task_id": task["id"], "identifier": task.get("identifier"), "title": title, "filed_at": monitor_state.now_iso(),
            }
            changed = True
            result["filed"] += 1
            created.append((task.get("identifier") or task["id"], title))
            log(f"filed {task.get('identifier') or task['id']}: {title}")
        if overflow and state.summary is None:
            title, body = summary_text(overflow, max_issues)
            task = client.create_task(title, body)
            state.summary = {"task_id": task["id"], "identifier": task.get("identifier")}
            changed = True
            created.append((task.get("identifier") or task["id"], title))
            log(f"filed summary {task.get('identifier') or task['id']}: {len(overflow)} waiting")
        elif overflow:
            log(f"summary {state.summary.get('identifier')} still open (tasks cannot be updated): {len(overflow)} waiting")
        elif state.summary:
            log(f"nothing waiting: summary {state.summary.get('identifier')} can be closed")
    finally:
        if watched:
            monitor_watch.advance(state, watched, {d.fingerprint for d in watched.devs if d.fingerprint in state.known()})
            changed = changed or json.dumps([state.names, state.sources], sort_keys=True) != baseline
        if changed:
            monitor_state.save(store, state, f"cotw-monitor: {result['filed']} filed, {decided} decided")
            log(f"state saved to {monitor_state.state_branch()}:{monitor_state.STATE_FILE}")
        if created and notify:
            file_digest(client, created, len(overflow), notify, log)
    return result


def file_digest(client, created: list[tuple[str, str]], overflow: int, notify: str, log=print) -> None:
    """One digest task for the run; a failure is logged, never raised (the state is saved)."""
    title, body = digest_text(created, overflow, notify, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        task = client.create_task(title, body)
        log(f"filed digest {task.get('identifier') or task.get('id')}: {title}")
    except Exception as exc:  # noqa: BLE001 - the findings are filed and saved; only the note is lost
        log(f"warning: digest task not filed: {exc}")


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
        log("names and naming sources: not checked without the state branch (or --state-file)")
        log("dry run without state: nothing touched")
        return 0
    store = gitea_cls(url, repo, token)
    if not cfg.notify:
        log("COTW_MONITOR_NOTIFY_ISSUE not set: no digest task")
    result = file_tasks(devs, client, store, max_issues, log, dry_run=dry_run, watch=report.get("watch"), notify=cfg.notify)
    if not dry_run:
        log(f"{result['filed']} filed, {result['known']} filed or decided before, {result['decided']} newly decided, {result['overflow']} in the summary")
    return 0


def check_local(path: str, max_issues: int, collect, log=print) -> int:
    """``check-wikidata --state-file PATH``: a dry run of the Paperclip sink against a local
    state file instead of the state branch (no Paperclip or Gitea access needed). Task statuses
    are not read and no task is filed; the seeded baseline is written to the file, so a second
    run compares against it."""
    devs, report = collect(log=log)
    log(f"{len(devs)} deviations ({report['rejected']} rejected via overrides, {report['damped']} damped)")
    log(f"state: local file {path} (dry run, task statuses not read)")
    file_tasks(devs, None, monitor_state.FileStore(path), max_issues, log, dry_run=True, watch=report.get("watch"), local=True)
    return 0
