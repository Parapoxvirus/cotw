"""Change monitoring (step 5): diff, damping, fingerprints, issue filing. Offline: the network
and Gitea are replaced by fixtures and fakes."""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone

import pytest
import yaml

from cotw import monitor, paths
from cotw.monitor import Deviation, Snapshot

NOW = datetime(2026, 9, 28, 5, 17, tzinfo=timezone.utc)
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40


@pytest.fixture(autouse=True)
def gitea_sink(monkeypatch):
    """These tests cover the default sink: Gitea issues, no Paperclip settings."""
    for name in ("PAPERCLIP_API_URL", "PAPERCLIP_API_KEY", "PAPERCLIP_COMPANY_ID", "PAPERCLIP_PROJECT_ID"):
        monkeypatch.delenv(name, raising=False)


def _entry(cid, iso2, iso3, qid, name_en, name_de, capital, cap_qid, lat, lon, de_title):
    return {
        "id": cid, "iso2": iso2, "iso3": iso3, "wikidata": qid, "status": "sovereign",
        "name": {"en-US": name_en, "de-CH": name_de},
        "capitals": [{"name": {"en-US": capital, "de-CH": capital}, "role": "capital", "wikidata": cap_qid, "lat": lat, "lon": lon}],
        "wikipedia": {"en-US": f"https://en.wikipedia.org/wiki/{name_en}", "de-CH": f"https://de.wikipedia.org/wiki/{de_title}"},
    }


ENTRIES = {
    "083": _entry("083", "DE", "DEU", "Q183", "Germany", "Deutschland", "Berlin", "Q64", 52.51667, 13.38333, "Deutschland"),
    "216": _entry("216", "CH", "CHE", "Q39", "Switzerland", "Schweiz", "Bern", "Q70", 46.94809, 7.44744, "Schweiz"),
}


def _cap(qid, label, coord, rank="ontology#normal", end=None, role=None):
    return {"qid": qid, "label_en-US": label, "label_de-CH": label, "coord": coord, "rank": rank, "start": None, "end": end,
            "role": None, "role_qid": role}


def _snapshot() -> Snapshot:
    return Snapshot(
        countries={
            "DE": [{"qid": "Q183", "iso3": "DEU", "label_en-US": "Germany", "label_de-CH": "Deutschland"}],
            "CH": [{"qid": "Q39", "iso3": "CHE", "label_en-US": "Switzerland", "label_de-CH": "Schweiz"}],
        },
        iso_codes={"DE": ["Q183"], "CH": ["Q39"], "XK": ["Q1246"]},
        capitals={"Q183": [_cap("Q64", "Berlin", [52.51667, 13.38333])], "Q39": [_cap("Q70", "Bern", [46.94809, 7.44744])]},
        coords={"Q64": [52.51667, 13.38333], "Q70": [46.94809, 7.44744]},
        status={},
        sitelinks={"Q183": {"en-US": "Germany", "de-CH": "Deutschland"}, "Q39": {"en-US": "Switzerland", "de-CH": "Schweiz"}},
        p41={
            "Q183": [{"file": "Flag of Germany.svg", "rank": "normal", "start": None, "end": None}],
            "Q39": [{"file": "Flag of Switzerland.svg", "rank": "preferred", "start": None, "end": None}],
        },
        commons={
            "Flag of Germany.svg": {"title": "Flag of Germany.svg", "license": "Public domain", "sha1": SHA_OLD, "page": "https://commons.wikimedia.org/wiki/File:Flag_of_Germany.svg"},
            "Flag of Switzerland.svg": {"title": "Flag of Switzerland.svg", "license": "Public domain", "sha1": SHA_OLD, "page": "https://commons.wikimedia.org/wiki/File:Flag_of_Switzerland.svg"},
        },
    )


MANIFEST = {
    "083": {"file": "Flag of Germany.svg", "license": "Public domain", "sha1": SHA_OLD},
    "216": {"file": "Flag of Switzerland.svg", "license": "Public domain", "sha1": SHA_OLD},
}
NO_OVERRIDES = {"capitals": {}, "flags": {}}


def run_diff(mutate, overrides=NO_OVERRIDES, base=None):
    base = base or _snapshot()
    live = copy.deepcopy(base)
    mutate(live)
    return monitor.diff(ENTRIES, base, live, overrides, MANIFEST)


def one(devs, kind) -> Deviation:
    found = [d for d in devs if d.kind == kind]
    assert len(found) == 1, [(d.kind, d.field) for d in devs]
    return found[0]


# --- diff ---------------------------------------------------------------------------------------


def test_identical_snapshots_have_no_deviations():
    assert run_diff(lambda live: None) == []


def test_iso3_change():
    def m(live):
        live.countries["DE"][0]["iso3"] = "DEX"

    d = one(run_diff(m), "iso3")
    assert (d.subject, d.field, d.old, d.new, d.item, d.prop) == ("083", "iso3", "DEU", "DEX", "Q183", "P298")


def test_capital_set_and_role_changes():
    def added(live):
        live.capitals["Q183"].append(_cap("Q1022", "Bonn", [50.73, 7.1], role="Q1901835"))

    d = one(run_diff(added), "capitals")
    assert d.new == ["Q64", "Q1022 role=Q1901835"] and d.old == ["Q64"]
    assert "Bonn (Q1022, role=Q1901835)" in d.new_text

    def ended(live):
        live.capitals["Q39"][0]["end"] = "2026-09-01T00:00:00Z"

    assert one(run_diff(ended), "capitals").new == []

    def deprecated(live):
        live.capitals["Q39"][0]["rank"] = "ontology#deprecated"

    assert one(run_diff(deprecated), "capitals").new == []

    def label_only(live):  # labels were never taken from Wikidata: no deviation
        live.capitals["Q39"][0]["label_en-US"] = "Berne"

    assert run_diff(label_only) == []


def test_capital_coordinates_tolerance():
    def noise(live):
        live.coords["Q64"] = [52.5199, 13.3855]  # ~0.4 km

    assert run_diff(noise) == []

    def moved(live):
        live.coords["Q64"] = [52.52, 13.405]  # ~1.5 km

    d = one(run_diff(moved), "coord")
    assert d.field == "capital Q64 coordinates" and d.new == [52.52, 13.405] and "km" in d.new_text


def test_capital_coordinates_fixed_by_override_are_not_reported():
    def moved(live):
        live.coords["Q64"] = [48.0, 11.0]

    ov = {"capitals": {"DE": {"Berlin": {"wikidata": "Q64", "lat": 52.5, "lon": 13.4, "reason": "x"}}}, "flags": {}}
    assert run_diff(moved, ov) == []
    # An override without coordinates (QID only) keeps them monitored.
    ov = {"capitals": {"DE": {"Berlin": {"wikidata": "Q64", "reason": "x"}}}, "flags": {}}
    assert one(run_diff(moved, ov), "coord")


def test_status_change():
    def m(live):
        live.status["Q39"] = {"P576": ["2026-09-20T00:00:00Z"], "P582": []}

    d = one(run_diff(m), "status")
    assert d.subject == "216" and d.prop == "P576|P582"


def test_sitelinks_en_and_de():
    def m(live):
        live.sitelinks["Q183"] = {"en-US": "Germany", "de-CH": "Bundesrepublik Deutschland"}

    d = one(run_diff(m), "sitelink")
    assert (d.field, d.old, d.new, d.prop) == ("wikipedia.de-CH", "Deutschland", "Bundesrepublik Deutschland", "sitelinks/dewiki")

    def removed(live):
        live.sitelinks["Q39"] = {"de-CH": "Schweiz"}

    d = one(run_diff(removed), "sitelink")
    assert (d.field, d.new) == ("wikipedia.en-US", None)


def test_flag_p41_change_and_override():
    def m(live):
        live.p41["Q183"] = [{"file": "Flag of Germany (new).svg", "rank": "preferred", "start": None, "end": None}]
        live.commons["Flag of Germany (new).svg"] = {"title": "Flag of Germany (new).svg", "license": "Public domain", "sha1": SHA_NEW, "page": "p"}

    d = one(run_diff(m), "flag-file")
    assert (d.old, d.new, d.alert) == ("Flag of Germany.svg", "Flag of Germany (new).svg", False)
    ov = {"capitals": {}, "flags": {"083": {"file": "Flag of Germany.svg", "reason": "x"}}}
    assert run_diff(m, ov) == []


def test_flag_p41_change_to_nonfree_file_stands_out():
    def m(live):
        live.p41["Q183"] = [{"file": "Flag of Germany (new).svg", "rank": "preferred", "start": None, "end": None}]
        live.commons["Flag of Germany (new).svg"] = {"title": "Flag of Germany (new).svg", "license": "CC BY-SA 4.0", "sha1": SHA_NEW, "page": "p"}

    d = one(run_diff(m), "flag-file")
    assert d.alert and d.title.startswith("NON-FREE") and "CC BY-SA 4.0" in d.new_text


def test_flag_ambiguous_p41():
    def m(live):
        live.p41["Q39"].append({"file": "Flag of Switzerland (Pantone).svg", "rank": "preferred", "start": None, "end": None})

    d = one(run_diff(m), "flag-file")
    assert d.new.startswith("several preferred-rank")


def test_commons_revision_and_license():
    def rev(live):
        live.commons["Flag of Germany.svg"]["sha1"] = SHA_NEW

    d = one(run_diff(rev), "flag-revision")
    assert (d.subject, d.item, d.entries, d.new) == ("File:Flag of Germany.svg", "File:Flag of Germany.svg", ["083"], SHA_NEW)

    def lic(live):
        live.commons["Flag of Germany.svg"]["license"] = "CC0"

    d = one(run_diff(lic), "flag-license")
    assert not d.alert

    def nonfree(live):
        live.commons["Flag of Germany.svg"]["license"] = "CC BY-SA 3.0"

    d = one(run_diff(nonfree), "flag-license")
    assert d.alert and d.title.startswith("NON-FREE")
    ov = {"capitals": {}, "flags": {"083": {"license": "CC BY-SA 3.0", "reason": "accepted"}}}
    assert not one(run_diff(nonfree, ov), "flag-license").alert

    def missing(live):
        live.commons["Flag of Germany.svg"] = {"missing": True}

    assert one(run_diff(missing), "flag-revision").new is None


def test_shared_flag_is_one_deviation():
    manifest = {**MANIFEST, "216": {"file": "Flag of Germany.svg", "license": "Public domain", "sha1": SHA_OLD}}
    base = _snapshot()
    live = copy.deepcopy(base)
    live.commons["Flag of Germany.svg"]["sha1"] = SHA_NEW
    d = one(monitor.diff(ENTRIES, base, live, NO_OVERRIDES, manifest), "flag-revision")
    assert d.entries == ["083", "216"]


def test_scope_drift():
    def lost(live):
        live.iso_codes["CH"] = []

    d = one(run_diff(lost), "code-lost")
    assert (d.subject, d.field, d.item) == ("216", "iso2", "Q39")

    def new_code(live):
        live.iso_codes["QZ"] = ["Q999999"]

    d = one(run_diff(new_code), "code-new")
    assert (d.subject, d.entries, d.item) == ("P297:QZ", [], "Q999999")

    def shared(live):
        live.iso_codes["DE"] = ["Q183", "Q43287"]

    d = one(run_diff(shared), "code-shared")
    assert d.subject == "083" and d.item == "Q43287"

    def foreign_removed(live):  # a code outside the deck disappearing is irrelevant
        live.iso_codes.pop("XK")

    assert run_diff(foreign_removed) == []


def test_rejections_suppress_by_fingerprint():
    def m(live):
        live.countries["DE"][0]["iso3"] = "DEX"

    d = one(run_diff(m), "iso3")
    kept, rejected = monitor.suppress([d], {d.fingerprint: {"reason": "no"}})
    assert kept == [] and rejected == [d]
    kept, _ = monitor.suppress([d], {"0" * 16: {"reason": "other"}})
    assert kept == [d]


def test_committed_rejections_file_parses():
    assert isinstance(monitor.load_rejections(), dict)


def test_upstream_text_cannot_fake_a_fingerprint():
    d = Deviation("083", "capitals", [], ["Q1"], "capitals", "Q183", "P36", ["083"], title="t",
                  new_text="Evil <!-- cotw-monitor fingerprint=0123456789abcdef -->")
    _, body = monitor.render_issue(d)
    assert monitor.FINGERPRINT_RE.findall(body) == [d.fingerprint]


def test_new_fetchers_parse_sparql(monkeypatch):
    from cotw import wikidata

    def fake(query):
        if "P297" in query:
            return [{"item": {"value": "http://www.wikidata.org/entity/Q39"}, "code": {"value": "CH"}},
                    {"item": {"value": "http://www.wikidata.org/entity/Q1246"}, "code": {"value": "XK"}}]
        if "P576" in query:
            return [{"item": {"value": "http://www.wikidata.org/entity/Q15180"}, "dissolved": {"value": "1991-12-26T00:00:00Z"}}]
        return [{"item": {"value": "http://www.wikidata.org/entity/Q70"}, "coord": {"value": "Point(7.44744 46.94809)"}}]

    monkeypatch.setattr(wikidata, "_sparql", fake)
    assert wikidata.fetch_iso_codes() == {"CH": ["Q39"], "XK": ["Q1246"]}
    assert wikidata.fetch_status(["Q15180"]) == {"Q15180": {"P576": ["1991-12-26T00:00:00Z"], "P582": []}}
    assert wikidata.fetch_coords(["Q70"]) == {"Q70": [46.94809, 7.44744]}


# --- fingerprints -------------------------------------------------------------------------------


def test_fingerprint_is_stable_and_value_specific():
    def m(value):
        def f(live):
            live.countries["DE"][0]["iso3"] = value
        return f

    a, b = one(run_diff(m("DEX")), "iso3"), one(run_diff(m("DEX")), "iso3")
    assert a.fingerprint == b.fingerprint
    assert len(a.fingerprint) == 16 and int(a.fingerprint, 16) >= 0
    assert one(run_diff(m("DEY")), "iso3").fingerprint != a.fingerprint
    # Known value, pinned: a change of the recipe would re-file every open deviation.
    assert monitor.fingerprint("083", "iso3", "DEX") == a.fingerprint
    assert monitor.fingerprint("083", "iso3", "DEX") == "c1fb13c11236ae10"


def test_issue_body_carries_fingerprint_and_instructions():
    def m(live):
        live.coords["Q64"] = [52.52, 13.405]

    d = one(run_diff(m), "coord")
    title, body = monitor.render_issue(d)
    assert monitor.FINGERPRINT_RE.findall(body) == [d.fingerprint]
    assert "Berlin" in title and "083" in body
    assert f"accept-wikidata {d.fingerprint}" in body and "monitoring.yaml" in body
    assert "https://www.wikidata.org/wiki/Q64" in body and "action=history" in body


# --- damping ------------------------------------------------------------------------------------


def _dev(item, prop="P36"):
    return Deviation("083", f"f-{item}-{prop}", None, "x", "capitals", item, prop, ["083"])


class FakeApi:
    """Answers the three damping queries from fixed data; counts calls."""

    def __init__(self, modified, revisions=None, touched=None):
        self.modified, self.revisions, self.touched, self.calls = modified, revisions or {}, touched or {}, []

    def __call__(self, url, params):
        self.calls.append(params)
        if params.get("action") == "wbgetentities":
            ids = params["ids"].split("|")
            return {"entities": {q: {"modified": self.modified[q]} for q in ids if q in self.modified}}
        if url == monitor.WIKIDATA_API:  # revisions: before cutoff (rvstart) or current
            q = params["titles"]
            ent = self.revisions[q][0 if "rvstart" in params else 1]
            revs = [{"slots": {"main": {"content": json.dumps(ent)}}}] if ent is not None else []
            return {"query": {"pages": [{"title": q, "revisions": revs}]}}
        titles = params["titles"].split("|")
        return {"query": {"pages": [{"title": t, "revisions": [{"timestamp": self.touched[t]}]} for t in titles if t in self.touched]}}


def test_damping_old_edit_is_kept():
    api = FakeApi({"Q183": "2026-09-20T10:00:00Z"})
    kept, damped = monitor.damp([_dev("Q183")], NOW, api)
    assert len(kept) == 1 and damped == []


def test_damping_recent_edit_to_the_property_is_damped():
    before = {"claims": {"P36": [{"id": "a", "mainsnak": {"datavalue": "Q64"}}]}}
    now = {"claims": {"P36": [{"id": "a", "mainsnak": {"datavalue": "Q1022"}}]}}
    api = FakeApi({"Q183": "2026-09-27T10:00:00Z"}, {"Q183": (before, now)})
    kept, damped = monitor.damp([_dev("Q183")], NOW, api)
    assert kept == [] and len(damped) == 1
    # the revision before the window is looked up at now - 72 h
    assert any(p.get("rvstart") == "2026-09-25T05:17:00Z" for p in api.calls)


def test_damping_recent_edit_elsewhere_on_the_item_is_kept():
    same = {"claims": {"P36": [{"id": "a"}]}, "sitelinks": {"dewiki": {"title": "Deutschland"}}}
    other = {"claims": {"P36": [{"id": "a"}], "P1082": [{"id": "pop"}]}, "sitelinks": {"dewiki": {"title": "Deutschland"}}}
    api = FakeApi({"Q183": "2026-09-27T10:00:00Z"}, {"Q183": (same, other)})
    kept, damped = monitor.damp([_dev("Q183"), _dev("Q183", "sitelinks/dewiki")], NOW, api)
    assert len(kept) == 2 and damped == []


def test_damping_new_item_is_damped():
    api = FakeApi({"Q999999": "2026-09-27T10:00:00Z"}, {"Q999999": (None, {"claims": {"P297": [{"id": "x"}]}})})
    _, damped = monitor.damp([_dev("Q999999", "P297")], NOW, api)
    assert len(damped) == 1


def test_damping_commons_file():
    recent = Deviation("File:A.svg", "flag revision", None, "x", "flag-revision", "File:A.svg", "file", ["083"])
    old = Deviation("File:B.svg", "flag revision", None, "x", "flag-revision", "File:B.svg", "file", ["216"])
    api = FakeApi({}, touched={"File:A.svg": "2026-09-27T00:00:00Z", "File:B.svg": "2026-01-01T00:00:00Z"})
    kept, damped = monitor.damp([recent, old], NOW, api)
    assert kept == [old] and damped == [recent]


# --- issues -------------------------------------------------------------------------------------


class FakeGitea:
    def __init__(self, issues=()):
        self._issues = [dict(i) for i in issues]
        self.writes: list[tuple] = []

    def repository(self):
        return {"permissions": {"admin": False, "push": True, "pull": True}}

    def issues(self):
        return [dict(i) for i in self._issues]

    def label_id(self, name):
        assert name == "wikidata"
        return 37

    def create_issue(self, title, body, labels):
        number = 100 + len(self._issues)
        self._issues.append({"number": number, "title": title, "body": body, "state": "open", "labels": labels})
        self.writes.append(("create", number, labels))
        return {"number": number}

    def edit_issue(self, number, **fields):
        self.writes.append(("edit", number, fields))
        for i in self._issues:
            if i["number"] == number:
                i.update(fields)
        return {"number": number}


def _devs(n, alert_at=None):
    return [
        Deviation(f"{i:03d}", "iso3", "OLD", f"N{i:02d}", "iso3", f"Q{i + 1}", "P298", [f"{i:03d}"], title=f"t{i}", alert=(i == alert_at))
        for i in range(n)
    ]


def test_filing_dedupes_against_open_and_closed_issues():
    devs = _devs(3)
    _, body0 = monitor.render_issue(devs[0])
    _, body1 = monitor.render_issue(devs[1])
    gitea = FakeGitea([{"number": 1, "body": body0, "state": "open"}, {"number": 2, "body": body1, "state": "closed"}])
    result = monitor.file_issues(devs, gitea, 20, log=lambda *_: None)
    assert result == {"known": 2, "filed": 1, "overflow": 0}
    assert [w for w in gitea.writes if w[0] == "create"] == [("create", 102, [37])]
    # a second run changes nothing
    gitea.writes.clear()
    assert monitor.file_issues(devs, gitea, 20, log=lambda *_: None)["filed"] == 0
    assert gitea.writes == []


def test_flood_cap_and_summary_issue_is_updated_not_duplicated():
    gitea = FakeGitea()
    devs = _devs(5, alert_at=4)
    result = monitor.file_issues(devs, gitea, 2, log=lambda *_: None)
    assert result == {"known": 0, "filed": 2, "overflow": 3}
    created = [i for i in gitea.issues()]
    assert len(created) == 3  # 2 deviations + 1 summary
    assert created[0]["title"] == "t4"  # the non-free alert jumps the queue
    summary = [i for i in created if monitor.SUMMARY_MARKER in i["body"]]
    assert len(summary) == 1 and "3 more" in summary[0]["title"]
    # next run: 2 more filed, the summary is edited in place
    result = monitor.file_issues(devs, gitea, 2, log=lambda *_: None)
    assert result == {"known": 2, "filed": 2, "overflow": 1}
    assert len([i for i in gitea.issues() if monitor.SUMMARY_MARKER in i["body"]]) == 1
    assert ("edit", summary[0]["number"]) in [(w[0], w[1]) for w in gitea.writes]
    # last run: nothing left over, the summary is closed
    monitor.file_issues(devs, gitea, 2, log=lambda *_: None)
    assert next(i for i in gitea.issues() if i["number"] == summary[0]["number"])["state"] == "closed"


def test_dry_run_never_writes(monkeypatch):
    gitea = FakeGitea()
    monkeypatch.setenv("COTW_MONITOR_TOKEN", "placeholder")
    monkeypatch.setattr(monitor, "collect", lambda log=print: (_devs(3), {"rejected": 0, "damped": 0}))
    monkeypatch.setattr(monitor, "Gitea", lambda *a: gitea)
    lines = []
    assert monitor.check(True, 2, "https://gitea.example.com", "owner/cotw", log=lines.append) == 0
    assert gitea.writes == []
    assert sum("[would file]" in line for line in lines) == 2 and sum("[summary]" in line for line in lines) == 1


def test_without_token_the_check_is_a_dry_run(monkeypatch):
    monkeypatch.delenv("COTW_MONITOR_TOKEN", raising=False)
    monkeypatch.setattr(monitor, "collect", lambda log=print: (_devs(1), {"rejected": 0, "damped": 0}))

    def no_gitea(*_):
        raise AssertionError("no Gitea client without a token")

    monkeypatch.setattr(monitor, "Gitea", no_gitea)
    monkeypatch.setattr(monitor, "file_issues", no_gitea)
    lines = []
    assert monitor.check(False, 20, "https://gitea.example.com", "owner/cotw", log=lines.append) == 0
    assert any("dry run" in line for line in lines)


def test_fetch_failure_writes_nothing(monkeypatch):
    gitea = FakeGitea()
    monkeypatch.setenv("COTW_MONITOR_TOKEN", "placeholder")
    monkeypatch.setattr(monitor, "Gitea", lambda *a: gitea)

    def boom(log=print):
        raise RuntimeError("SPARQL failed after 4 attempts")

    monkeypatch.setattr(monitor, "collect", boom)
    with pytest.raises(RuntimeError):
        monitor.check(False, 20, "https://gitea.example.com", "owner/cotw", log=lambda *_: None)
    assert gitea.writes == []


# --- accept -------------------------------------------------------------------------------------


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Caches + one entry copied to a temp dir; accept() writes there."""
    wd = tmp_path / "data" / "wikidata"
    shutil.copytree(paths.WIKIDATA, wd)
    countries = tmp_path / "data" / "countries"
    countries.mkdir()
    src = next(paths.COUNTRIES.glob("083-*.yaml"))
    shutil.copy(src, countries / src.name)
    monkeypatch.setattr(paths, "WIKIDATA", wd)
    monkeypatch.setattr(monitor, "COUNTRIES", countries)
    return wd, countries / src.name


def _accept_with(monkeypatch, dev, live):
    monkeypatch.setattr(monitor, "collect", lambda log=print: ([dev], {"rejected": 0, "damped": 0, "live": live}))
    lines = []
    assert monitor.accept(dev.fingerprint, log=lines.append) == 0
    return lines


def test_accept_coordinates_updates_caches_and_entry(monkeypatch, sandbox):
    wd, entry_path = sandbox
    base = monitor.load_baseline()
    live = copy.deepcopy(base)
    live.coords["Q64"] = [52.52, 13.405]
    d = one(monitor.diff({"083": yaml.safe_load(entry_path.read_text(encoding="utf-8"))}, base, live, NO_OVERRIDES, {}), "coord")
    other_before = json.loads((wd / "capitals.json").read_text(encoding="utf-8"))
    lines = _accept_with(monkeypatch, d, live)
    caps = json.loads((wd / "capitals.json").read_text(encoding="utf-8"))
    assert caps["Q183"][0]["coord"] == [52.52, 13.405]
    assert {k: v for k, v in caps.items() if k != "Q183"} == {k: v for k, v in other_before.items() if k != "Q183"}
    entry = yaml.safe_load(entry_path.read_text(encoding="utf-8"))
    assert (entry["capitals"][0]["lat"], entry["capitals"][0]["lon"]) == (52.52, 13.405)
    assert any("build-maps 083" in line for line in lines)


def test_accept_dewiki_sitelink(monkeypatch, sandbox):
    wd, entry_path = sandbox
    base = monitor.load_baseline()
    live = copy.deepcopy(base)
    live.sitelinks["Q183"] = {**live.sitelinks["Q183"], "de-CH": "Bundesrepublik Deutschland"}
    d = one(monitor.diff({"083": yaml.safe_load(entry_path.read_text(encoding="utf-8"))}, base, live, NO_OVERRIDES, {}), "sitelink")
    _accept_with(monkeypatch, d, live)
    assert json.loads((wd / "sitelinks.json").read_text(encoding="utf-8"))["Q183"]["de-CH"] == "Bundesrepublik Deutschland"
    entry = yaml.safe_load(entry_path.read_text(encoding="utf-8"))
    assert entry["wikipedia"]["de-CH"] == "https://de.wikipedia.org/wiki/Bundesrepublik_Deutschland"


def test_accept_unknown_fingerprint_fails(monkeypatch):
    monkeypatch.setattr(monitor, "collect", lambda log=print: ([], {"rejected": 0, "damped": 0, "live": None}))
    assert monitor.accept("0" * 16, log=lambda *_: None) == 1


# --- committed baseline + workflow --------------------------------------------------------------


def test_committed_baseline_loads_and_matches_itself():
    base = monitor.load_baseline()
    assert base.iso_codes and base.capitals and base.p41 and base.commons
    entries = monitor.load_entries()
    assert monitor.diff(entries, base, copy.deepcopy(base)) == []
    # every capital the deck places on a map has baseline coordinates, unless an override fixes them
    fixed = {
        ov["wikidata"]
        for caps in monitor.load_domain_overrides()["capitals"].values()
        for ov in caps.values()
        if ov.get("lat") is not None
    }
    assert set(monitor.capital_qids(entries)) - set(base.coords) <= fixed


def test_workflow_is_scheduled_and_dispatchable():
    wf = yaml.safe_load((paths.ROOT / ".gitea" / "workflows" / "wikidata-check.yml").read_text(encoding="utf-8"))
    on = wf.get("on", wf.get(True))  # PyYAML reads a bare `on:` key as True
    assert "schedule" in on and "workflow_dispatch" in on
    minute, hour, dom, month, dow = on["schedule"][0]["cron"].split()
    assert minute not in ("0", "00", "30") and dow in ("1", "MON", "mon")
    assert "dry_run" in on["workflow_dispatch"]["inputs"]
    job = next(iter(wf["jobs"].values()))
    assert job["container"] == "node:20-bookworm"
    text = json.dumps(wf)
    assert "setup-python" not in text and "check-wikidata" in text and "COTW_MONITOR_TOKEN" in text
