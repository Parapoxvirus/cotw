"""Name and naming-source monitoring (docs/MONITORING.md, *Names and naming sources*).

Two checks that need a baseline the repository does not hold, so they run only with the state
of the Paperclip sink (``monitor_state``: ``names`` and ``sources``):

- **names**: the Wikidata label of every entry item and every capital item in every Wikidata
  label language of the registered locales (their chains in ``data/locales.yaml``: ``en``,
  ``de-ch``, ``de``), and the official names (P1448) of every entry item, against the values
  last seen;
- **sources**: a signature of every watched official naming source (``monitor_sources``).

The baseline is what Wikidata (or the source) said last time, never COTW's names, so the known
differences between COTW and Wikidata never show up. Its label keys are Wikidata languages
(``labels/de``), not locales; a finding links the sections of the locales that read the
language. A key missing from the baseline (first run, a new locale or chain language, a new
entry or capital) is seeded silently. A changed key is a
finding; its baseline moves only when the finding is filed (or was filed or decided before),
so damped and overflowing findings come back next run.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

from . import languages, monitor_sources, wikidata
from .monitor import Deviation, _get_json, _history, _name, _wd, load_rejections, recent, suppress
from .paths import ROOT

DROP = object()  # update value: remove the key
FAILURES_FOR_FINDING = 3
TRANSLATING = ROOT / "docs" / "TRANSLATING.md"

REMINDER = (
    "**A Wikidata label is a signal, not a source.** Check the change against the official list for the language in "
    "`docs/TRANSLATING.md` ({sections}) and apply official changes as soon as possible (*Source rule*), in the "
    "language's spelling (de-CH: Swiss spelling, ss)."
)


@dataclass
class Watched:
    """What the checks found and how the baseline moves."""

    devs: list[Deviation] = field(default_factory=list)
    always: list[tuple] = field(default_factory=list)  # (section, key, part, value): seeding, pruning, failure counts
    on_filed: dict[str, list[tuple]] = field(default_factory=dict)  # fingerprint → updates once filed or known
    rejected: set[str] = field(default_factory=set)
    seeded: dict[str, int] = field(default_factory=lambda: {"names": 0, "sources": 0})
    damped: int = 0


def apply(state, updates) -> None:
    for section, key, part, value in updates:
        bucket = getattr(state, section)
        if value is DROP:
            if part is None:
                bucket.pop(key, None)
            else:
                bucket.get(key, {}).pop(part, None)
                if key in bucket and not bucket[key]:
                    del bucket[key]
        else:
            bucket.setdefault(key, {})[part] = value


def advance(state, watched: Watched, done: set[str], dry_run: bool = False) -> None:
    """Move the baseline: the unconditional updates, and the keys of every finding in ``done``
    (filed now, filed or decided before, or rejected). A key shared by several findings (a
    capital of several entries) moves only when all of them are done. In a dry run only the
    unconditional updates are applied (used with a local state file)."""
    apply(state, watched.always)
    if dry_run:
        return
    done = done | watched.rejected
    by_key: dict[tuple, list[tuple[str, tuple]]] = {}
    for fp, updates in watched.on_filed.items():
        for u in updates:
            by_key.setdefault(u[:3], []).append((fp, u))
    apply(state, [pairs[0][1] for pairs in by_key.values() if all(fp in done for fp, _ in pairs)])


# --- TRANSLATING.md sections --------------------------------------------------------------------


def _slug(heading: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"[^\w\s-]", "", heading.strip().lower()))


def sections() -> dict[str, str]:
    """Locale (lower case) → anchor of its *Naming sources* subsection (``### German (DE-CH)``)."""
    text = TRANSLATING.read_text(encoding="utf-8") if TRANSLATING.exists() else ""
    heading = r"^### (.+) \(([A-Z]{2,3}(?:-[A-Z0-9]+)*)\)$"
    return {m.group(2).lower(): _slug(m.group(0)[4:]) for m in re.finditer(heading, text, re.M)}


def docs_url(anchor: str) -> str:
    """Link to a TRANSLATING.md section: on the repository's web UI in CI, else the path."""
    server, repo = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY")
    if server and repo:
        ref = os.environ.get("GITHUB_REF_NAME") or "main"
        kind = "blob" if "github.com" in server else "src/branch"
        return f"{server.rstrip('/')}/{repo}/{kind}/{ref}/docs/TRANSLATING.md#{anchor}"
    return f"docs/TRANSLATING.md#{anchor}"


def section_links(codes) -> list[tuple[str, str]]:
    """Links to the *Naming sources* sections of these locales (``de-CH``)."""
    known = sections()
    out = [(f"TRANSLATING.md: {code.upper()}", docs_url(known[code.lower()])) for code in sorted(set(codes)) if code.lower() in known]
    return out or [("TRANSLATING.md: Naming sources", docs_url("naming-sources"))]


def reminder(links: list[tuple[str, str]]) -> str:
    return REMINDER.format(sections=", ".join(f"[{label.split(': ', 1)[1]}]({url})" for label, url in links))


# --- names --------------------------------------------------------------------------------------


def locales_reading(langs) -> list[str]:
    """The registered locales whose Wikidata chain has one of these label languages (``de`` →
    ``de-CH``); a P1448 language no locale reads (``fr``) maps to none."""
    langs = set(langs)
    return [code for code in languages.LANGUAGES if langs & set(wikidata.chain(code))]


def watched_names(entries: dict) -> dict[str, dict]:
    """``{qid: {"parts": [...], "what": "<name> (entry|capital)"}}`` for every entry and capital item."""
    labels = [f"labels/{lang}" for lang in wikidata.label_languages()]
    out: dict[str, dict] = {}
    for e in entries.values():
        out[e["wikidata"]] = {"parts": labels + ["P1448"], "what": f"{e['name'][languages.BASE]} (entry)"}
    for e in entries.values():
        for cap in e["capitals"]:
            q = cap.get("wikidata")
            if q and q not in out:
                out[q] = {"parts": list(labels), "what": f"{cap['name'][languages.BASE]} (capital)"}
    return out


def fetch_official_names(qids: list[str]) -> dict[str, list[str]]:
    """Current official names (P1448: not deprecated, no end time) per item as ``"<lang>: <name>"``."""
    out: dict[str, set[str]] = {q: set() for q in qids}
    for chunk in wikidata._chunks(sorted(set(qids), key=lambda q: int(q[1:])), 50):
        values = " ".join(f"wd:{q}" for q in chunk)
        query = f"""
        SELECT ?item ?name ?rank WHERE {{
          VALUES ?item {{ {values} }}
          ?item p:P1448 ?st . ?st ps:P1448 ?name . ?st wikibase:rank ?rank .
          FILTER(?rank != wikibase:DeprecatedRank)
          FILTER NOT EXISTS {{ ?st pq:P582 ?end }}
        }}"""
        for b in wikidata._sparql(query):
            if b["rank"]["value"].endswith("#DeprecatedRank"):
                continue
            out.setdefault(wikidata._qid(b["item"]["value"]), set()).add(f"{b['name'].get('xml:lang', '?')}: {b['name']['value']}")
    return {q: sorted(v) for q, v in out.items()}


def fetch_names(watch: dict[str, dict]) -> dict[str, dict]:
    """The live values of every watched key (network: Wikidata API and SPARQL)."""
    qids = sorted(watch, key=lambda q: int(q[1:]))
    labels = wikidata.fetch_label_values(qids, wikidata.label_languages())
    official = fetch_official_names([q for q in qids if "P1448" in watch[q]["parts"]])
    live: dict[str, dict] = {}
    for q in qids:
        for part in watch[q]["parts"]:
            if part == "P1448":
                live.setdefault(q, {})[part] = official.get(q, [])
            else:
                live.setdefault(q, {})[part] = (labels.get(q) or {}).get(part.split("/", 1)[1])
    return live


def _fmt_name(value) -> str:
    return "none" if value is None else f"“{value}”"


def _change_line(what: str, q: str, part: str, old, new) -> str:
    if part == "P1448":
        added, removed = sorted(set(new or []) - set(old or [])), sorted(set(old or []) - set(new or []))
        diff = "; ".join([f"added {v}" for v in added] + [f"removed {v}" for v in removed]) or "reordered"
        return f"{q} {what} · official name (P1448) · {diff}"
    return f"{q} {what} · label · {part.split('/', 1)[1]}: {_fmt_name(old)} → {_fmt_name(new)}"


def _codes(part: str, old, new) -> set[str]:
    if part == "P1448":
        return {v.split(":", 1)[0] for v in set(old or []) ^ set(new or [])}
    return {part.split("/", 1)[1]}


def check_names(entries: dict, baseline: dict, live: dict, watch: dict) -> tuple[list[tuple[Deviation, list[tuple], list[tuple]]], list[tuple], int]:
    """``(findings, always, seeded)``: one finding per entry with changed values, as
    ``(deviation, [(qid, part)], updates)``; the unconditional updates (seeding new keys,
    dropping keys no longer watched); the number of seeded keys."""
    always: list[tuple] = []
    seeded = 0
    changed: dict[tuple[str, str], tuple] = {}
    for q, info in watch.items():
        base = baseline.get(q) or {}
        for part in info["parts"]:
            value = live.get(q, {}).get(part)
            if part not in base:
                always.append(("names", q, part, value))
                seeded += 1
            elif base[part] != value:
                changed[(q, part)] = (base[part], value)
        for part in set(base) - set(info["parts"]):
            always.append(("names", q, part, DROP))
    for q in set(baseline) - set(watch):
        always.append(("names", q, None, DROP))

    findings = []
    for cid, e in sorted(entries.items()):
        items = [e["wikidata"]] + [c["wikidata"] for c in e["capitals"] if c.get("wikidata")]
        keys = [(q, p) for q in dict.fromkeys(items) for p in watch[q]["parts"] if (q, p) in changed]
        if not keys:
            continue
        lines = [_change_line(watch[q]["what"], q, p, *changed[(q, p)]) for q, p in keys]
        new = sorted(f"{q} {p}={changed[(q, p)][1]}" for q, p in keys)
        codes = set().union(*(_codes(p, *changed[(q, p)]) for q, p in keys))
        links = section_links(locales_reading(codes))
        item_links = [_wd(q) for q in dict.fromkeys(q for q, _ in keys)] + [_history(keys[0][0])]
        d = Deviation(
            cid, "names", None, new, "names", e["wikidata"], "names", [cid],
            title=f"{_name(e)}: names changed on Wikidata",
            old_text="; ".join(f"{q} {p}: {_fmt_name(changed[(q, p)][0])}" for q, p in keys),
            new_text="; ".join(f"{q} {p}: {_fmt_name(changed[(q, p)][1])}" for q, p in keys),
            links=item_links + links,
            impact="Possibly `name.<code>`, `formal_name` or `capitals[].name.<code>` of this entry, if an official source has the change."
            " A changed capital statement (P36) is reported separately as a capitals deviation.",
            changes=lines,
            reminder=reminder(links),
        )
        findings.append((d, keys, [("names", q, p, changed[(q, p)][1]) for q, p in keys]))
    return findings, always, seeded


# --- naming sources -----------------------------------------------------------------------------


def check_sources(baseline: dict, results: dict, now_iso: str) -> tuple[list[tuple[Deviation, list[tuple]]], list[tuple], int, list[str]]:
    """``(findings, always, seeded, failed)``. ``results``: source id → ``(signature, info)`` or
    the exception of a failed fetch."""
    findings, always, seeded, failed = [], [], 0, []
    for s in monitor_sources.SOURCES:
        rec = baseline.get(s.id) or {}
        result = results.get(s.id)
        links = [(s.title, s.link)] + section_links(s.languages)
        if isinstance(result, BaseException) or result is None:
            n, since = int(rec.get("failures") or 0) + 1, rec.get("failing_since") or now_iso
            error = str(result)[:200] if result is not None else "not fetched"
            always += [("sources", s.id, "failures", n), ("sources", s.id, "failing_since", since), ("sources", s.id, "error", error)]
            failed.append(s.id)
            if n >= FAILURES_FOR_FINDING:
                findings.append((Deviation(
                    f"source:{s.id}", "unreachable", None, since, "source-unreachable", f"source:{s.id}", "", [],
                    title=f"Naming source unreachable since {since[:10]}: {s.title} ({s.publisher})",
                    old_text="reachable", new_text=f"{n} failed runs since {since}",
                    changes=[f"{n} weekly runs in a row could not fetch {s.url}", f"last error: {error}"],
                    links=links,
                    impact=f"Nothing in the deck. New editions of this source ({', '.join(c.upper() for c in s.languages)}) are not noticed until it is reachable again.",
                ), []))
            continue
        sig, info = result
        if rec.get("failures"):
            always += [("sources", s.id, k, DROP) for k in ("failures", "failing_since", "error")]
        if "signature" not in rec:
            always += [("sources", s.id, "signature", sig), ("sources", s.id, "since", now_iso)]
            seeded += 1
        elif rec["signature"] != sig:
            extra = [f"{k.replace('_', '-')}: {v}" for k, v in sorted(info.items())]
            d = Deviation(
                f"source:{s.id}", "edition", rec["signature"], sig, "edition", f"source:{s.id}", "", [],
                title=f"Naming source {s.title} ({s.publisher}): new edition or update",
                old_text=monitor_sources.describe(rec["signature"]), new_text=monitor_sources.describe(sig),
                changes=[f"source: {s.title}, {s.publisher} ({s.role}; decides or cross-checks {', '.join(c.upper() for c in s.languages)})",
                         f"seen since {rec.get('since', '?')}: {monitor_sources.describe(rec['signature'])}",
                         f"now: {monitor_sources.describe(sig)}",
                         *monitor_sources.compare(rec["signature"], sig), *extra],
                links=links,
                impact=f"Possibly the {'/'.join(c.upper() for c in s.languages)} names of any entry or capital: check the entries against the new edition.",
                reminder=reminder(section_links(s.languages)),
            )
            findings.append((d, [("sources", s.id, "signature", sig), ("sources", s.id, "since", now_iso)]))
    for sid in set(baseline) - {s.id for s in monitor_sources.SOURCES}:
        always.append(("sources", sid, None, DROP))
    return findings, always, seeded, failed


def fetch_sources(fetch=monitor_sources.fetch, log=print) -> dict:
    """Every watched source; a failure is recorded and logged, never raised."""
    out = {}
    for s in monitor_sources.SOURCES:
        try:
            out[s.id] = fetch(s)
        except Exception as exc:  # noqa: BLE001 - official sites must never fail the run
            log(f"warning: naming source {s.id} not fetched: {type(exc).__name__}: {str(exc)[:200]}")
            out[s.id] = exc
    return out


# --- one run ------------------------------------------------------------------------------------


def run(state, entries: dict, now: datetime, log=print, names_fetch=fetch_names, source_fetch=monitor_sources.fetch, get=None) -> Watched:
    """Both checks against ``state.names``/``state.sources`` (network). Wikidata failures raise
    like the rest of the check; naming-source failures are counted."""
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    watched = Watched()
    watch = watched_names(entries)
    live = names_fetch(watch)
    name_findings, always, watched.seeded["names"] = check_names(entries, state.names, live, watch)
    watched.always += always
    if name_findings:
        hot = recent(sorted({k for _, keys, _ in name_findings for k in keys}), now, get or _get_json)
        for d, keys, updates in name_findings:
            if any(k in hot for k in keys):
                watched.damped += 1
                log(f"damped (changed < 72 h ago, next run): {d.title}")
                continue
            watched.devs.append(d)
            watched.on_filed[d.fingerprint] = updates
    results = fetch_sources(source_fetch, log)
    src_findings, always, watched.seeded["sources"], failed = check_sources(state.sources, results, now_iso)
    watched.always += always
    for d, updates in src_findings:
        watched.devs.append(d)
        watched.on_filed[d.fingerprint] = updates
    watched.devs, rejected = suppress(watched.devs, load_rejections())
    watched.rejected = {d.fingerprint for d in rejected}
    keys = sum(len(v["parts"]) for v in watch.values())
    log(f"names: {keys} Wikidata values of {len(watch)} items watched, {watched.seeded['names']} seeded, "
        f"{sum(d.kind == 'names' for d in watched.devs)} entries with changes, {watched.damped} damped")
    log(f"naming sources: {len(monitor_sources.SOURCES)} watched, {watched.seeded['sources']} seeded, "
        f"{sum(d.kind == 'edition' for d in watched.devs)} new editions, {len(failed)} not reachable"
        + (f" ({', '.join(failed)})" if failed else ""))
    return watched
