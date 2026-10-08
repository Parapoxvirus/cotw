"""The official naming sources of docs/TRANSLATING.md, watched for new editions (docs/MONITORING.md).

Each source has a **signature** that changes with a new edition or update and ignores volatile
page parts (session ids, navigation, generated element ids):

- ``document``: one file (PDF, …): SHA-256 and size of the body. ``ETag`` and ``Last-Modified``
  are recorded for the finding text, not compared (servers change them without a new file).
- ``links``: a page listing the documents: the sorted set of linked document URLs (a new
  edition or update is a new file or a new attachment id), never a hash of the page.
- ``govuk``: a GOV.UK publication through its content API: the stated ``public_updated_at`` and
  the sorted attachment URLs.
- ``table``: a page carrying the list itself: SHA-256 of the table cell texts (whitespace
  normalized, markup ignored) and the row count.

Fetch failures of these sites never fail the run; ``monitor_watch`` counts them.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser

from . import locales
from .wikidata import USER_AGENT

TIMEOUT = 60
DOCUMENT_EXT = re.compile(r"\.(pdf|xlsx?|docx?|odt|ods|csv|zip)$", re.I)
# Links that are documents without a file extension: gov.pl attachments.
DOCUMENT_PATH = re.compile(r"^/attachment/[0-9a-f-]+$")


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    publisher: str
    languages: tuple[str, ...]  # the locales (data/locales.yaml) whose names it decides or cross-checks
    url: str  # what is fetched
    method: str  # document | links | govuk | table
    page: str = ""  # what a person opens, if not ``url``
    role: str = ""  # its role, as in docs/TRANSLATING.md

    @property
    def link(self) -> str:
        return self.page or self.url


GOVUK_API = "https://www.gov.uk/api/content"
EU_A5 = "https://style-guide.europa.eu/o/opportal-service/isg?resource={lang}/annex-a5-list-countries-territories-currencies.html"
EU_A5_PAGE = "https://style-guide.europa.eu/{lang}/content/-/isg/topic?identifier=annex-a5-list-countries-territories-currencies"

# The locales the EU list cross-checks. Its language code is the locale's language subtag
# (``de-CH`` → ``de``), looked up in data/locales.yaml so that only listed locales qualify.
EU_A5_LOCALES = ("en-US", "de-CH", "pl-PL")


def eu_language(tag: str) -> str:
    return locales.get(tag).tag.split("-", 1)[0]


SOURCES: tuple[Source, ...] = (
    Source("eda", "Liste der Staatenbezeichnungen", "EDA (Swiss FDFA)", ("de-CH",),
           "https://www.eda.admin.ch/dam/de/sd-web/viWGvPDY5NYo/liste-etats_DE.pdf", "document", role="DE-CH primary"),
    Source("auswaertiges-amt", "Verzeichnis der Staatennamen für den amtlichen Gebrauch", "Auswärtiges Amt", ("de-CH",),
           "https://www.auswaertiges-amt.de/de/service/terminologie/215252-215252", "links", role="DE-CH cross-check"),
    Source("stagn", "Liste der Staatennamen und ihrer Ableitungen im Deutschen", "StAGN", ("de-CH",),
           "https://stagn.bkg.bund.de/was-wir-veroeffentlichen/uebersichten-listen-und-datenbanken/synoptische-staatennamenliste",
           "links", role="DE-CH cross-check"),
    Source("bk-schreibweisungen", "Schreibweisungen", "Swiss Federal Chancellery", ("de-CH",),
           "https://www.bk.admin.ch/de/schreibweisungen", "links", role="DE-CH spelling rule"),
    Source("bk-rechtschreibleitfaden", "Rechtschreibleitfaden", "Swiss Federal Chancellery", ("de-CH",),
           "https://www.bk.admin.ch/de/rechtschreibleitfaden", "links", role="DE-CH spelling rule"),
    Source("ksng-states", "Urzędowy wykaz nazw państw i terytoriów niesamodzielnych", "KSNG", ("pl-PL",),
           "https://www.gov.pl/web/ksng/Urzedowy-wykaz-nazw-panstw-i-terytoriow-niesamodzielnych", "links",
           role="PL-PL primary (with its update documents)"),
    Source("ksng-world", "Urzędowy wykaz polskich nazw geograficznych świata", "KSNG", ("pl-PL",),
           "https://www.gov.pl/web/ksng/urzedowy-wykaz-polskich-nazw-geograficznych-swiata2", "links",
           role="PL-PL supplement (with its list of changes)"),
    Source("funag-toponimos", "Topônimos e gentílicos", "Fundação Alexandre de Gusmão (FUNAG)", ("pt-BR",),
           "https://funag.gov.br/manual/index.php?title=Top%C3%B4nimos_e_gent%C3%ADlicos", "table",
           role="PT-BR supplement / accessible official reproduction"),
    Source("pcgn-country-names", "Country names", "PCGN (UK)", ("en-US",),
           f"{GOVUK_API}/government/publications/country-names", "govuk",
           page="https://www.gov.uk/government/publications/country-names", role="EN-US cross-check"),
    Source("fcdo-geographical-names", "Geographical names index", "FCDO with PCGN (UK)", ("en-US",),
           f"{GOVUK_API}/government/publications/geographical-names-and-information", "govuk",
           page="https://www.gov.uk/government/publications/geographical-names-and-information", role="EN-US cross-check, territories"),
    *(
        Source(f"eu-annex-a5-{lang}", f"Interinstitutional Style Guide, Annex A5 ({lang.upper()})", "Publications Office of the EU",
               (tag,), EU_A5.format(lang=lang), "table", page=EU_A5_PAGE.format(lang=lang), role=f"{tag.upper()} cross-check")
        for tag, lang in ((tag, eu_language(tag)) for tag in EU_A5_LOCALES)
    ),
)

# Naming sources of docs/TRANSLATING.md that are not watched, with the reason (a test checks
# that every link of its *Naming sources* section is either watched or listed here).
NOT_WATCHED: dict[str, str] = {
    "https://www.gov.br/mre/pt-br/arquivos/manual-de-redacao": "the MRE page challenges automated clients; "
    "the official FUNAG reproduction of its country-name table is watched instead",
    "https://unterm.un.org/": "UNTERM is a JavaScript application without a documented public API; "
    "UN renamings also reach Wikidata, the national lists and the EU list, which are watched",
    "https://www.state.gov/independent-states-in-the-world/": "the State Department site refuses automated clients (HTTP 403)",
    "https://www.state.gov/dependencies-and-areas-of-special-sovereignty/": "the State Department site refuses automated clients (HTTP 403)",
    "https://www.iso.org/iso-3166-country-codes.html": "iso.org refuses automated clients (HTTP 403) and the Online Browsing Platform "
    "needs JavaScript; the codes are watched through P297/P298 on Wikidata",
}


def by_id() -> dict[str, Source]:
    return {s.id: s for s in SOURCES}


# --- signatures (pure: tested with recorded fixtures) --------------------------------------------


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def document_links(html: str, base: str) -> list[str]:
    """Sorted absolute URLs of the documents a page links to (fragments and duplicates dropped)."""
    parser = _Links()
    parser.feed(html)
    out = set()
    for href in parser.hrefs:
        url = urllib.parse.urljoin(base, href.strip()).split("#", 1)[0]
        path = urllib.parse.urlsplit(url).path
        if DOCUMENT_EXT.search(urllib.parse.unquote(path)) or DOCUMENT_PATH.match(path):
            out.add(url)
    return sorted(out)


class _Cells(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag == "tr":
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def table_rows(html: str) -> list[str]:
    """The non-empty table rows of a page as text, cells separated by `` | ``."""
    parser = _Cells()
    parser.feed(html)
    return [" | ".join(r) for r in parser.rows if any(r)]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def signature(source: Source, body: bytes, headers: dict[str, str]) -> tuple[dict, dict]:
    """``(signature, info)`` of one fetched response. ``info`` is shown, never compared."""
    headers = {k.lower(): v for k, v in headers.items()}
    info = {k: headers[h] for k, h in (("etag", "etag"), ("last_modified", "last-modified")) if headers.get(h)}
    if source.method == "document":
        return {"sha256": _sha256(body), "size": len(body)}, info
    text = body.decode("utf-8", "replace")
    if source.method == "links":
        return {"documents": document_links(text, source.url)}, info
    if source.method == "govuk":
        data = json.loads(text)
        attachments = (data.get("details") or {}).get("attachments") or []
        docs = sorted({urllib.parse.urljoin("https://www.gov.uk/", a["url"]) for a in attachments if a.get("url")})
        return {"updated": data.get("public_updated_at"), "documents": docs}, info
    if source.method == "table":
        rows = table_rows(text)
        return {"sha256": _sha256("\n".join(rows).encode("utf-8")), "rows": len(rows)}, info
    raise ValueError(f"unknown method {source.method!r}")


def describe(sig: dict | None) -> str:
    """Short text of a signature for the finding."""
    if not sig:
        return "none"
    parts = []
    if sig.get("updated"):
        parts.append(f"updated {sig['updated']}")
    if "documents" in sig:
        parts.append(f"{len(sig['documents'])} documents")
    if "rows" in sig:
        parts.append(f"{sig['rows']} table rows")
    if "size" in sig:
        parts.append(f"{sig['size']} bytes")
    if sig.get("sha256"):
        parts.append(f"sha256 {sig['sha256'][:12]}")
    return ", ".join(parts)


def compare(old: dict, new: dict) -> list[str]:
    """What differs between two signatures, one line each (documents added/removed by URL)."""
    out = []
    old_docs, new_docs = set(old.get("documents") or []), set(new.get("documents") or [])
    out += [f"new document: {u}" for u in sorted(new_docs - old_docs)]
    out += [f"document gone: {u}" for u in sorted(old_docs - new_docs)]
    for key in ("updated", "rows", "size", "sha256"):
        if old.get(key) != new.get(key) and (key in old or key in new):
            out.append(f"{key}: {old.get(key)} → {new.get(key)}")
    return out


# --- fetching (network) --------------------------------------------------------------------------


def fetch(source: Source, get=None) -> tuple[dict, dict]:
    """Fetch one source and return its signature; raises on any failure (the caller counts it)."""
    if get is None:
        import requests

        def get(url):
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.content, dict(resp.headers)

    body, headers = get(source.url)
    return signature(source, body, headers)
