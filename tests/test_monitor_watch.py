"""Name and naming-source monitoring (monitor_watch): seeding, findings against the baseline in
the state, damping, the flood cap, the 3-failure rule, the reminder text and the digest task.
Offline: Wikidata, the official sites and Paperclip are fakes."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from cotw import languages, monitor, monitor_paperclip, monitor_sources, monitor_state, monitor_watch
from test_monitor_paperclip import FakePaperclip, FakeStore

NOW = datetime(2026, 9, 28, 5, 17, tzinfo=timezone.utc)
QUIET = dict(log=lambda *_: None)
REMINDER_START = "**A Wikidata label is a signal, not a source.**"


def _entries():
    return {
        "083": {"id": "083", "wikidata": "Q183", "name": {"en-US": "Germany", "de-CH": "Deutschland"},
                "capitals": [{"wikidata": "Q64", "name": {"en-US": "Berlin", "de-CH": "Berlin"}}]},
        "216": {"id": "216", "wikidata": "Q697", "name": {"en-US": "Nauru", "de-CH": "Nauru"},
                "capitals": [{"wikidata": "Q31026", "name": {"en-US": "Yaren", "de-CH": "Yaren"}}]},
    }


def _live():
    """Wikidata as fetched now (labels may differ from COTW: only the baseline counts). Keyed by
    Wikidata language: ``de-ch`` (first in the de-CH chain) has no label on these items."""
    return {
        "Q183": {"labels/en": "Germany", "labels/de": "Deutschland", "P1448": ["de: Bundesrepublik Deutschland"]},
        "Q64": {"labels/en": "Berlin", "labels/de": "Berlin"},
        "Q697": {"labels/en": "Nauru", "labels/de": "Nauru", "P1448": ["en: Republic of Nauru", "na: Repubrikin Naoero"]},
        "Q31026": {"labels/en": "Yaren District", "labels/de": "Yaren"},
    }


def _v2_baseline():
    """The names baseline as the state branch holds it before the locale codes (state version 2):
    labels per Wikidata language of the old codes (``labels/en``, ``labels/de``) and P1448."""
    return {q: dict(parts) for q, parts in _live().items()}


def _sources_ok(sig=None):
    def fetch(source):
        return (sig or {"documents": [f"https://example.com/{source.id}.pdf"]}), {}

    return fetch


class QuietApi:
    """Damping look-ups: nothing was edited in the last 72 h unless listed in ``hot``."""

    def __init__(self, hot=()):
        self.hot = dict(hot)  # qid → (entity 72 h ago, entity now)

    def __call__(self, url, params):
        if params.get("action") == "wbgetentities":
            ids = params["ids"].split("|")
            return {"entities": {q: {"modified": "2026-09-27T10:00:00Z" if q in self.hot else "2026-09-01T10:00:00Z"} for q in ids}}
        q = params["titles"]
        ent = self.hot[q][0 if "rvstart" in params else 1]
        return {"query": {"pages": [{"title": q, "revisions": [{"slots": {"main": {"content": json.dumps(ent)}}}]}]}}


def _run(state, live=None, sources=None, api=None, log=None):
    live = live if live is not None else _live()
    return monitor_watch.run(
        state, _entries(), NOW, log or (lambda *_: None),
        names_fetch=lambda watch: {q: dict(live.get(q, {})) for q in watch},
        source_fetch=sources or _sources_ok(), get=api or QuietApi(),
    )


def _seeded_state(live=None):
    state = monitor_state.State()
    monitor_watch.advance(state, _run(state, live), set())
    return state


@pytest.fixture(autouse=True)
def two_languages(monkeypatch):
    monkeypatch.setattr(languages, "LANGUAGES", ("en-US", "de-CH"))


# --- names --------------------------------------------------------------------------------------


def test_first_run_seeds_silently():
    state = monitor_state.State()
    lines = []
    watched = _run(state, log=lines.append)
    # entries: en, de-ch, de and P1448; capitals: the three labels
    assert watched.devs == [] and watched.seeded == {"names": 2 * 4 + 2 * 3, "sources": len(monitor_sources.SOURCES)}
    assert any("14 seeded" in line for line in lines) and any(f"{len(monitor_sources.SOURCES)} seeded" in line for line in lines)
    monitor_watch.advance(state, watched, set())
    assert state.names["Q31026"] == {"labels/en": "Yaren District", "labels/de-ch": None, "labels/de": "Yaren"}  # Wikidata's value, not COTW's
    assert state.names["Q697"]["P1448"] == ["en: Republic of Nauru", "na: Repubrikin Naoero"]
    assert set(state.sources) == {s.id for s in monitor_sources.SOURCES}


def test_watched_labels_are_the_wikidata_languages_of_the_locales():
    watch = monitor_watch.watched_names(_entries())
    assert watch["Q697"]["parts"] == ["labels/en", "labels/de-ch", "labels/de", "P1448"]
    assert watch["Q31026"]["parts"] == ["labels/en", "labels/de-ch", "labels/de"]
    assert monitor_watch.locales_reading(["de"]) == monitor_watch.locales_reading(["de-ch"]) == ["de-CH"]
    assert monitor_watch.locales_reading(["en", "fr", "na"]) == ["en-US"]


def test_v2_baseline_with_unchanged_values_gives_no_findings_under_the_locale_codes():
    """No state migration: the baseline written with the codes ``en``/``de`` keeps its keys, the
    new chain language ``de-ch`` is seeded silently, nothing is dropped and nothing is filed."""
    state = monitor_state.State()
    state.names = _v2_baseline()
    for s in monitor_sources.SOURCES:
        state.sources[s.id] = {"signature": {"documents": [f"https://example.com/{s.id}.pdf"]}, "since": "2026-09-21T05:17:00Z"}
    watched = _run(state)
    assert watched.devs == [] and watched.damped == 0
    assert watched.seeded == {"names": 4, "sources": 0}
    assert sorted(watched.always) == sorted(("names", q, "labels/de-ch", None) for q in _live())
    monitor_watch.advance(state, watched, set())
    assert all(state.names[q] == {**_live()[q], "labels/de-ch": None} for q in _live())
    assert _run(state).devs == []


def test_baseline_equal_to_live_gives_no_findings():
    state = _seeded_state()
    before = json.dumps(state.to_json())
    watched = _run(state)
    assert watched.devs == [] and watched.seeded == {"names": 0, "sources": 0}
    monitor_watch.advance(state, watched, set())
    assert json.dumps(state.to_json()) == before


def test_one_changed_label_is_exactly_one_finding_for_its_entry():
    state = _seeded_state()
    live = _live()
    live["Q697"]["labels/en"] = "Naoero"
    watched = _run(state, live)
    assert len(watched.devs) == 1
    d = watched.devs[0]
    assert d.kind == "names" and d.entries == ["216"] and d.subject == "216"
    assert d.changes == ["Q697 Nauru (entry) · label · en: “Nauru” → “Naoero”"]
    title, body = monitor.render_issue(d)
    assert title == "216 Nauru: names changed on Wikidata"
    assert monitor.FINGERPRINT_RE.findall(body) == [d.fingerprint]
    assert "“Nauru” → “Naoero”" in body and REMINDER_START in body
    assert "docs/TRANSLATING.md#english-en-us" in body
    assert "accept-wikidata` does not apply" in body
    # same change next week: same fingerprint
    assert _run(state, live).devs[0].fingerprint == d.fingerprint


def test_label_and_capital_and_p1448_of_one_entry_are_one_finding():
    state = _seeded_state()
    live = _live()
    live["Q697"]["labels/de"] = "Naoero"
    live["Q697"]["P1448"] = ["en: Republic of Naoero", "na: Repubrikin Naoero"]
    live["Q31026"]["labels/en"] = "Yaren"
    watched = _run(state, live)
    assert [d.entries for d in watched.devs] == [["216"]]
    lines = watched.devs[0].changes
    assert len(lines) == 3
    assert "Q697 Nauru (entry) · official name (P1448) · added en: Republic of Naoero; removed en: Republic of Nauru" in lines
    assert "Q31026 Yaren (capital) · label · en: “Yaren District” → “Yaren”" in lines
    body = monitor.render_issue(watched.devs[0])[1]
    assert "english-en-us" in body and "german-de-ch" in body


def test_removed_label_is_a_finding():
    state = _seeded_state()
    live = _live()
    del live["Q64"]["labels/de"]
    watched = _run(state, live)
    assert len(watched.devs) == 1 and watched.devs[0].entries == ["083"]
    assert watched.devs[0].changes == ["Q64 Berlin (capital) · label · de: “Berlin” → none"]


def test_filed_finding_moves_the_baseline():
    state = _seeded_state()
    live = _live()
    live["Q697"]["labels/en"] = "Naoero"
    watched = _run(state, live)
    monitor_watch.advance(state, watched, {watched.devs[0].fingerprint})
    assert state.names["Q697"]["labels/en"] == "Naoero"
    assert _run(state, live).devs == []


def test_damped_change_is_not_reported_and_keeps_the_baseline():
    state = _seeded_state()
    live = _live()
    live["Q697"]["labels/en"] = "Naoero"
    api = QuietApi({"Q697": ({"labels": {"en": {"value": "Nauru"}}}, {"labels": {"en": {"value": "Naoero"}}})})
    lines = []
    watched = _run(state, live, api=api, log=lines.append)
    assert watched.devs == [] and watched.damped == 1
    assert any(line.startswith("damped") and "216 Nauru" in line for line in lines)
    monitor_watch.advance(state, watched, set())
    assert state.names["Q697"]["labels/en"] == "Nauru"  # comes back next run
    assert len(_run(state, live).devs) == 1


def test_recent_edit_of_another_label_does_not_damp():
    state = _seeded_state()
    live = _live()
    live["Q697"]["labels/en"] = "Naoero"
    same_en = ({"labels": {"en": {"value": "Naoero"}, "fr": {"value": "Nauru"}}}, {"labels": {"en": {"value": "Naoero"}, "fr": {"value": "Naoero"}}})
    watched = _run(state, live, api=QuietApi({"Q697": same_en}))
    assert len(watched.devs) == 1 and watched.damped == 0


def test_new_language_module_is_seeded_silently(monkeypatch):
    state = _seeded_state()
    monkeypatch.setattr(languages, "LANGUAGES", ("en-US", "de-CH", "pl-PL"))
    live = _live()
    for q, label in (("Q183", "Niemcy"), ("Q64", "Berlin"), ("Q697", "Nauru"), ("Q31026", "Yaren")):
        live[q]["labels/pl"] = label
    watched = _run(state, live)
    assert watched.devs == [] and watched.seeded["names"] == 4
    monitor_watch.advance(state, watched, set())
    assert state.names["Q183"]["labels/pl"] == "Niemcy"
    live["Q697"]["labels/pl"] = "Naoero"
    d = _run(state, live).devs[0]
    assert d.changes == ["Q697 Nauru (entry) · label · pl: “Nauru” → “Naoero”"]
    assert "polish-pl-pl" in monitor.render_issue(d)[1]


def test_items_no_longer_watched_are_dropped_from_the_baseline():
    state = _seeded_state()
    state.names["Q999"] = {"labels/en": "Old capital"}
    state.names["Q183"]["labels/xx"] = "gone"
    watched = _run(state)
    assert watched.devs == []
    monitor_watch.advance(state, watched, set())
    assert "Q999" not in state.names and "labels/xx" not in state.names["Q183"]


def test_capital_shared_by_two_entries_moves_only_when_both_are_filed():
    entries = _entries()
    entries["216"]["capitals"].append({"wikidata": "Q64", "name": {"en-US": "Berlin", "de-CH": "Berlin"}})
    live = _live()

    def run(state, live):
        return monitor_watch.run(state, entries, NOW, lambda *_: None,
                                 names_fetch=lambda watch: {q: dict(live.get(q, {})) for q in watch},
                                 source_fetch=_sources_ok(), get=QuietApi())

    state = monitor_state.State()
    monitor_watch.advance(state, run(state, live), set())
    live["Q64"]["labels/en"] = "Berlin City"
    watched = run(state, live)
    assert sorted(d.subject for d in watched.devs) == ["083", "216"]
    monitor_watch.advance(state, watched, {watched.devs[0].fingerprint})
    assert state.names["Q64"]["labels/en"] == "Berlin"
    monitor_watch.advance(state, watched, {d.fingerprint for d in watched.devs})
    assert state.names["Q64"]["labels/en"] == "Berlin City"


# --- naming sources -----------------------------------------------------------------------------


def test_changed_source_signature_is_one_edition_finding():
    state = _seeded_state()
    eda = {"sha256": "1" * 64, "size": 100}
    state.sources["eda"]["signature"] = eda

    def fetch(source):
        return ({"sha256": "2" * 64, "size": 120} if source.id == "eda" else {"documents": [f"https://example.com/{source.id}.pdf"]}), {"etag": '"x"'}

    watched = _run(state, sources=fetch)
    assert [d.kind for d in watched.devs] == ["edition"]
    d = watched.devs[0]
    assert "Liste der Staatenbezeichnungen" in d.title
    body = monitor.render_issue(d)[1]
    assert REMINDER_START in body and "docs/TRANSLATING.md#german-de-ch" in body
    assert "size: 100 → 120" in body and "etag: \"x\"" in body
    monitor_watch.advance(state, watched, {d.fingerprint})
    assert state.sources["eda"]["signature"] == {"sha256": "2" * 64, "size": 120}


def test_source_failures_never_fail_the_run_and_three_in_a_row_are_one_finding():
    state = _seeded_state()

    def fetch(source):
        if source.id == "stagn":
            raise OSError("connection timed out")
        return {"documents": [f"https://example.com/{source.id}.pdf"]}, {}

    lines = []
    for run in (1, 2):
        watched = _run(state, sources=fetch, log=lines.append)
        assert watched.devs == []
        monitor_watch.advance(state, watched, set())
        assert state.sources["stagn"]["failures"] == run and "signature" in state.sources["stagn"]
    assert any("warning: naming source stagn not fetched" in line for line in lines)
    watched = _run(state, sources=fetch)
    assert [d.kind for d in watched.devs] == ["source-unreachable"]
    body = monitor.render_issue(watched.devs[0])[1]
    assert "3 weekly runs in a row" in body and "connection timed out" in body
    monitor_watch.advance(state, watched, set())
    # the same outage gives the same fingerprint (filed once); recovering resets the count
    assert _run(state, sources=fetch).devs[0].fingerprint == watched.devs[0].fingerprint
    monitor_watch.advance(state, _run(state), set())
    assert "failures" not in state.sources["stagn"]


def test_first_sight_of_a_source_while_unreachable_seeds_later():
    state = monitor_state.State()

    def broken(source):
        raise OSError("down")

    monitor_watch.advance(state, _run(state, sources=broken), set())
    assert all("signature" not in rec for rec in state.sources.values())
    watched = _run(state)
    assert watched.devs == [] and watched.seeded["sources"] == len(monitor_sources.SOURCES)


# --- through the Paperclip sink: baseline moves, flood cap, digest -----------------------------


def _watch(live=None, sources=None, api=None):
    return lambda state, log: _run(state, live, sources, api, log)


def _iso_devs(n):
    return [monitor.Deviation(f"{i:03d}", "iso3", "OLD", f"N{i:02d}", "iso3", f"Q{i + 1}", "P298", [f"{i:03d}"], title=f"Änderung {i}")
            for i in range(n)]


def test_first_real_run_seeds_the_state_branch_and_files_nothing():
    store, pc = FakeStore(), FakePaperclip()
    monitor_paperclip.file_tasks([], pc, store, 20, watch=_watch(), notify="ABC-1", **QUIET)
    assert pc.created == []  # no findings: no task, no digest
    data = store.state()
    assert data["version"] == 2 and data["names"]["Q697"]["labels/en"] == "Nauru" and len(data["sources"]) == len(monitor_sources.SOURCES)


def test_overflow_keeps_the_baseline_and_comes_back():
    store, pc = FakeStore(), FakePaperclip()
    monitor_paperclip.file_tasks([], pc, store, 20, watch=_watch(), **QUIET)
    live = _live()
    live["Q697"]["labels/en"] = "Naoero"  # "216 …" sorts after the iso3 deviations "000", "001"
    monitor_paperclip.file_tasks(_iso_devs(2), pc, store, 2, watch=_watch(live), **QUIET)
    assert [t["title"] for t in pc.created][:2] == ["Änderung 0", "Änderung 1"]
    assert store.state()["names"]["Q697"]["labels/en"] == "Nauru"  # in the summary, not filed
    monitor_paperclip.file_tasks(_iso_devs(2), pc, store, 2, watch=_watch(live), **QUIET)
    assert pc.created[-1]["title"] == "216 Nauru: names changed on Wikidata"
    assert store.state()["names"]["Q697"]["labels/en"] == "Naoero"


def test_dry_run_against_the_state_branch_writes_nothing():
    store, pc = FakeStore(), FakePaperclip()
    lines = []
    monitor_paperclip.file_tasks([], pc, store, 20, log=lines.append, dry_run=True, watch=_watch(), notify="ABC-1")
    assert store.writes == [] and pc.created == []
    assert any("14 seeded" in line for line in lines)


def test_local_state_file_seeds_then_compares(tmp_path):
    path = tmp_path / "state.json"
    lines = []
    for _ in range(2):
        monitor_paperclip.file_tasks([], None, monitor_state.FileStore(path), 20, log=lines.append, dry_run=True, watch=_watch(), local=True)
    assert sum("would file" in line for line in lines) == 0
    assert sum("seeded baseline written" in line for line in lines) == 1  # second pass: nothing new
    data = json.loads(path.read_text(encoding="utf-8"))
    data["names"]["Q697"]["labels/en"] = "Nauru (old)"
    path.write_text(json.dumps(data), encoding="utf-8")
    lines.clear()
    monitor_paperclip.file_tasks([], None, monitor_state.FileStore(path), 20, log=lines.append, dry_run=True, watch=_watch(), local=True)
    assert sum("[would file]" in line for line in lines) == 1
    assert any(REMINDER_START in line for line in lines)
    assert json.loads(path.read_text(encoding="utf-8"))["names"]["Q697"]["labels/en"] == "Nauru (old)"  # a finding never moves it in a dry run


def test_digest_is_filed_once_when_tasks_were_filed():
    store, pc = FakeStore(), FakePaperclip()
    monitor_paperclip.file_tasks([], pc, store, 20, watch=_watch(), notify="ABC-1", **QUIET)
    live = _live()
    live["Q697"]["labels/en"] = "Naoero"
    monitor_paperclip.file_tasks(_iso_devs(3), pc, store, 2, watch=_watch(live), notify="ABC-1", **QUIET)
    digests = [t for t in pc.created if t["title"].startswith("cotw monitor:")]
    assert len(digests) == 1 and pc.created[-1]["id"] == digests[0]["id"]
    d = digests[0]
    assert d["title"].startswith("cotw monitor: 2 new findings (")
    assert "one comment on ABC-1" in d["description"] and "mark this task done" in d["description"]
    for t in pc.created[:-1]:  # two findings and the summary
        assert f"- {t['identifier']}: {t['title']}" in d["description"]
    assert "2 more waiting" in d["description"]
    assert not monitor.FINGERPRINT_RE.search(d["description"])
    assert len(store.state()["filed"]) == 2  # the digest is not tracked
    # the next run files the rest: one more digest; then nothing new: none
    monitor_paperclip.file_tasks(_iso_devs(3), pc, store, 20, watch=_watch(live), notify="ABC-1", **QUIET)
    digests = [t for t in pc.created if t["title"].startswith("cotw monitor:")]
    assert len(digests) == 2 and "216 Nauru: names changed on Wikidata" in digests[1]["description"]
    n = len(pc.created)
    monitor_paperclip.file_tasks(_iso_devs(3), pc, store, 20, watch=_watch(live), notify="ABC-1", **QUIET)
    assert len(pc.created) == n


def test_no_digest_without_notify_issue_or_in_a_dry_run():
    store, pc = FakeStore(), FakePaperclip()
    monitor_paperclip.file_tasks(_iso_devs(1), pc, store, 20, **QUIET)
    assert [t["title"] for t in pc.created] == ["Änderung 0"]
    monitor_paperclip.file_tasks(_iso_devs(2), pc, store, 20, dry_run=True, notify="ABC-1", **QUIET)
    assert len(pc.created) == 1


def test_digest_failure_is_logged_and_the_state_is_saved():
    store, pc = FakeStore(), FakePaperclip(fail_after=1)
    lines = []
    monitor_paperclip.file_tasks(_iso_devs(1), pc, store, 20, log=lines.append, notify="ABC-1")
    assert len(pc.created) == 1 and len(store.state()["filed"]) == 1
    assert any(line.startswith("warning: digest task not filed") for line in lines)


def test_notify_issue_from_env(monkeypatch):
    from test_monitor_paperclip import PAPERCLIP_ENV

    for name, value in PAPERCLIP_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("COTW_MONITOR_NOTIFY_ISSUE", raising=False)
    assert monitor_paperclip.config().notify is None
    monkeypatch.setenv("COTW_MONITOR_NOTIFY_ISSUE", "ABC-1")
    assert monitor_paperclip.config().notify == "ABC-1"


def test_accept_steps_cover_the_new_kinds():
    for kind in ("names", "edition", "source-unreachable"):
        d = monitor.Deviation("216", kind, None, "x", kind, "Q697", "names", ["216"])
        steps = monitor.accept_steps(d)
        assert steps and not any("accept-wikidata" in s for s in steps)


def test_fetch_official_names_skips_deprecated_statements(monkeypatch):
    rank = "http://wikiba.se/ontology#{}Rank".format
    rows = [
        ("Q183", "de", "Bundesrepublik Deutschland", "Normal"),
        ("Q183", "en", "Federal Republic of Germany", "Preferred"),
        ("Q183", "eo", "Federacia Respubliko Germanio", "Deprecated"),
        ("Q697", "na", "Repubrikin Naoero", "Normal"),
    ]
    queries = []

    def fake_sparql(query):
        queries.append(query)
        return [{"item": {"value": f"http://www.wikidata.org/entity/{q}"},
                 "name": {"xml:lang": lang, "value": name}, "rank": {"value": rank(r)}} for q, lang, name, r in rows]

    monkeypatch.setattr(monitor_watch.wikidata, "_sparql", fake_sparql)
    got = monitor_watch.fetch_official_names(["Q697", "Q183", "Q64"])
    assert got == {
        "Q183": ["de: Bundesrepublik Deutschland", "en: Federal Republic of Germany"],
        "Q64": [],
        "Q697": ["na: Repubrikin Naoero"],
    }
    assert len(queries) == 1 and "FILTER(?rank != wikibase:DeprecatedRank)" in queries[0]
