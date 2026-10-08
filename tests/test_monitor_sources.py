"""Official naming sources (monitor_sources): coverage of docs/TRANSLATING.md and the
signature extraction. Offline: the fixtures are trimmed responses recorded on 2026-10-06."""

from __future__ import annotations

import json
import re

import pytest

from cotw import monitor_sources, paths
from cotw.monitor_sources import NOT_WATCHED, SOURCES

FIXTURES = paths.ROOT / "tests" / "fixtures" / "monitor_sources"


def _source(sid):
    return monitor_sources.by_id()[sid]


def _sig(sid, name, headers=None):
    return monitor_sources.signature(_source(sid), (FIXTURES / name).read_bytes(), headers or {})


def _naming_source_urls() -> list[str]:
    text = (paths.ROOT / "docs" / "TRANSLATING.md").read_text(encoding="utf-8")
    section = text.split("## Naming sources", 1)[1].split("### Helpers, not naming sources", 1)[0]
    return sorted(set(re.findall(r"\]\((https?://[^)\s]+)\)", section)))


def test_every_naming_source_is_watched_or_listed_as_not_watched():
    urls = _naming_source_urls()
    assert len(urls) >= 12
    watched = {s.link for s in SOURCES} | {s.url for s in SOURCES}
    missing = [u for u in urls if u not in watched and u not in NOT_WATCHED]
    assert missing == [], f"neither watched nor listed in NOT_WATCHED: {missing}"
    assert set(NOT_WATCHED) <= set(urls)  # no stale exceptions


def test_monitoring_doc_lists_every_source():
    doc = (paths.ROOT / "docs" / "MONITORING.md").read_text(encoding="utf-8")
    for s in SOURCES:
        assert s.title.split(" (")[0] in doc and f"`{s.id}`" in doc, s.id  # EU Annex A5: one row, three ids
    for url in NOT_WATCHED:
        assert url in doc, url


def test_source_records_are_consistent():
    assert len({s.id for s in SOURCES}) == len(SOURCES)
    for s in SOURCES:
        assert s.method in ("document", "links", "govuk", "table")
        assert s.url.startswith("https://") and s.languages


def test_links_signature_ignores_volatile_markup():
    # Two fetches of the same page: generated container ids and the embedded app state differ.
    raw1, raw2 = (FIXTURES / "bk-schreibweisungen-1.html").read_bytes(), (FIXTURES / "bk-schreibweisungen-2.html").read_bytes()
    assert raw1 != raw2
    sig1, _ = _sig("bk-schreibweisungen", "bk-schreibweisungen-1.html")
    sig2, _ = _sig("bk-schreibweisungen", "bk-schreibweisungen-2.html")
    assert sig1 == sig2
    assert len(sig1["documents"]) == 3 and all(u.startswith("https://www.bk.admin.ch/dam/") for u in sig1["documents"])
    assert "https://www.bk.admin.ch/dam/de/sd-web/YVHazXZRkqKn/schreibweisungen.pdf" in sig1["documents"]


def test_links_signature_changes_with_a_new_document():
    page = (FIXTURES / "auswaertiges-amt.html").read_text(encoding="utf-8")
    sig, _ = monitor_sources.signature(_source("auswaertiges-amt"), page.encode(), {})
    assert [u.rsplit("/", 1)[1] for u in sig["documents"]] == ["staatennamen-data.pdf", "nutzungshinweise-data.pdf", "xlsx-data.xlsx", "ods-data.ods"]
    assert all(u.startswith("https://www.auswaertiges-amt.de/resource/blob/") for u in sig["documents"])
    # a new edition is a new blob: the signature changes, the comparison names the documents
    new_page = page.replace("/resource/blob/199312/1f90428274b6cbbff078d9714bb38eae/staatennamen-data.pdf",
                            "/resource/blob/300000/0123456789abcdef0123456789abcdef/staatennamen-data.pdf")
    new, _ = monitor_sources.signature(_source("auswaertiges-amt"), new_page.encode(), {})
    assert new != sig
    lines = monitor_sources.compare(sig, new)
    assert any(line.startswith("new document: ") and "300000" in line for line in lines)
    assert any(line.startswith("document gone: ") and "199312" in line for line in lines)


def test_gov_pl_attachments_are_documents():
    sig, _ = _sig("ksng-states", "ksng-states.html")
    assert len(sig["documents"]) == 4
    assert all(re.fullmatch(r"https://www\.gov\.pl/attachment/[0-9a-f-]{36}", u) for u in sig["documents"])


def test_govuk_signature_uses_the_public_date_and_attachments():
    sig, _ = _sig("pcgn-country-names", "pcgn-country-names.json")
    assert sig["updated"] == "2026-07-20T16:44:20+01:00"
    assert len(sig["documents"]) == 3 and all(u.startswith("https://") for u in sig["documents"])
    data = json.loads((FIXTURES / "pcgn-country-names.json").read_text(encoding="utf-8"))
    data["updated_at"] = "2026-10-01T00:00:00+01:00"  # republishing without a public change
    same, _ = monitor_sources.signature(_source("pcgn-country-names"), json.dumps(data).encode(), {})
    assert same == sig
    data["public_updated_at"] = "2026-11-02T10:00:00+00:00"
    changed, _ = monitor_sources.signature(_source("pcgn-country-names"), json.dumps(data).encode(), {})
    assert changed != sig and "updated: 2026-07-20T16:44:20+01:00 → 2026-11-02T10:00:00+00:00" in monitor_sources.compare(sig, changed)


def test_table_signature_ignores_markup_but_not_names():
    html = (FIXTURES / "eu-annex-a5-en.html").read_text(encoding="utf-8")
    sig, _ = monitor_sources.signature(_source("eu-annex-a5-en"), html.encode(), {})
    assert sig["rows"] == 4  # header + Afghanistan, Nauru, Switzerland
    rows = monitor_sources.table_rows(html)
    assert rows[0].startswith("Short name | Full name | Country code(1)")
    assert any(r.startswith("Nauru | Republic of Nauru | NR | Yaren") for r in rows)
    # regenerated ids, attributes and whitespace: same signature
    noisy = re.sub(r'id="id5000500', 'id="d99999e1', html).replace('class="row"', 'class="row odd"').replace("> <", ">\n  <")
    assert monitor_sources.signature(_source("eu-annex-a5-en"), noisy.encode(), {})[0] == sig
    # a renamed entry: new signature
    renamed = html.replace(">Nauru<", ">Naoero<").replace("Republic of Nauru", "Republic of Naoero")
    new, _ = monitor_sources.signature(_source("eu-annex-a5-en"), renamed.encode(), {})
    assert new != sig and new["rows"] == sig["rows"]


def test_funag_table_signature_covers_brazilian_portuguese_names():
    sig, _ = _sig("funag-toponimos", "funag-toponimos.html")
    rows = monitor_sources.table_rows((FIXTURES / "funag-toponimos.html").read_text(encoding="utf-8"))
    assert sig["rows"] == 4
    assert rows[0] == "Forma breve | Nome oficial | Capital | Gentílico"
    assert any(row.startswith("Essuatíni | Reino de Essuatíni | Mbabane") for row in rows)


def test_document_signature_is_the_content_not_the_headers():
    body = b"%PDF-1.7 Liste der Staatenbezeichnungen (example)"
    sig, info = monitor_sources.signature(_source("eda"), body, {"ETag": '"abc"', "Last-Modified": "Fri, 21 Aug 2026 14:27:22 GMT"})
    assert sig == {"sha256": monitor_sources._sha256(body), "size": len(body)}
    assert info == {"etag": '"abc"', "last_modified": "Fri, 21 Aug 2026 14:27:22 GMT"}
    again, _ = monitor_sources.signature(_source("eda"), body, {"ETag": '"other"'})
    assert again == sig
    assert monitor_sources.signature(_source("eda"), body + b" 2", {})[0] != sig


def test_fetch_uses_the_given_getter_and_raises_on_failure():
    calls = []

    def get(url):
        calls.append(url)
        return (FIXTURES / "ksng-states.html").read_bytes(), {}

    sig, _ = monitor_sources.fetch(_source("ksng-states"), get)
    assert calls == [_source("ksng-states").url] and len(sig["documents"]) == 4

    def broken(url):
        raise OSError("connection refused")

    with pytest.raises(OSError):
        monitor_sources.fetch(_source("ksng-states"), broken)


# One recorded response per watched source (EDA is a PDF: its signature is the body, see above).
FIXTURE_OF = {
    "auswaertiges-amt": ("auswaertiges-amt.html", 4),
    "stagn": ("stagn.html", 1),
    "bk-schreibweisungen": ("bk-schreibweisungen-1.html", 3),
    "bk-rechtschreibleitfaden": ("bk-rechtschreibleitfaden.html", 1),
    "ksng-states": ("ksng-states.html", 4),
    "ksng-world": ("ksng-world.html", 6),
    "pcgn-country-names": ("pcgn-country-names.json", 3),
    "fcdo-geographical-names": ("fcdo-geographical-names.json", 4),
}

TABLE_FIXTURE_OF = {
    "funag-toponimos": "funag-toponimos.html",
}


@pytest.mark.parametrize("sid", [s.id for s in SOURCES])
def test_every_watched_source_has_a_recorded_fixture(sid):
    source = _source(sid)
    if source.method == "document":
        assert sid == "eda"  # covered by test_document_signature_is_the_content_not_the_headers
        return
    if source.method == "table":
        name = TABLE_FIXTURE_OF.get(sid, "eu-annex-a5-en.html")
        sig, _ = _sig(sid, name)  # the three EU languages share the recorded EN page layout
        assert sig["rows"] == 4
        return
    name, n = FIXTURE_OF[sid]
    sig, _ = _sig(sid, name)
    assert len(sig["documents"]) == n and all(u.startswith("https://") for u in sig["documents"])
    assert monitor_sources.describe(sig).startswith(("updated ", f"{n} documents"))


def test_stagn_edition_is_the_file_name():
    sig, _ = _sig("stagn", "stagn.html")
    assert sig["documents"][0].endswith("/STAATENNAMEN_15.pdf")  # 15th edition; the 16th is a new file


def test_fcdo_signature():
    sig, _ = _sig("fcdo-geographical-names", "fcdo-geographical-names.json")
    assert sig["updated"] == "2026-09-15T13:29:28+01:00"
    assert any(u.endswith("FCDO_Geographical_Names_Index_July2026.csv") for u in sig["documents"])
