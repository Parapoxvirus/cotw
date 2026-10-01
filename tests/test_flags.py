"""Flag selection, license gate and SVG cleanup on synthetic inputs (offline)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cotw import flags


def test_commons_title_decodes_file_path():
    uri = "http://commons.wikimedia.org/wiki/Special:FilePath/Flag%20of%20M%C3%BC%C3%9Fig.svg"
    assert flags.commons_title(uri) == "Flag of Müßig.svg"


def test_select_prefers_preferred_rank():
    statements = [
        {"file": "Old flag.svg", "rank": "normal", "start": None, "end": "1990"},
        {"file": "Flag of Mätzlingen.svg", "rank": "preferred", "start": None, "end": None},
    ]
    assert flags.select_file(statements) == ("Flag of Mätzlingen.svg", "preferred rank")


def test_select_single_current_normal_statement():
    statements = [
        {"file": "Old.svg", "rank": "normal", "start": None, "end": "1990"},
        {"file": "Current.svg", "rank": "normal", "start": None, "end": None},
        {"file": "Wrong.svg", "rank": "deprecated", "start": None, "end": None},
    ]
    assert flags.select_file(statements)[0] == "Current.svg"


def test_select_ambiguous_or_missing_needs_override():
    two = [{"file": f, "rank": "preferred", "start": None, "end": None} for f in ("A.svg", "B.svg")]
    assert flags.select_file(two)[0] is None
    assert flags.select_file([{"file": "X.svg", "rank": "deprecated", "start": None, "end": None}])[0] is None
    assert flags.select_file([])[0] is None


def test_license_gate():
    assert flags.license_allowed("Public domain")
    assert flags.license_allowed("PD-self")
    assert flags.license_allowed("CC0")
    for lic in ("CC BY-SA 4.0", "CC BY 2.5", "OGL-om 1.0", "", None):
        assert not flags.license_allowed(lic)


def test_strip_removes_metadata_and_renames_ids():
    svg = (
        '<?xml version="1.0"?>\n<!-- Flag of Jürgen Groß Land -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" sodipodi:docname="Flag_of_Mätzlingen.svg">\n'
        "<title>Flag of Mätzlingen</title><desc>Mätzlingen</desc><metadata><rdf:RDF/></metadata>\n"
        '<defs><linearGradient id="Flag_of_Mätzlingen_gradient"/><path id="star_of_Groß" d="M0 0h1v1z"/></defs>\n'
        '<rect fill="url(#Flag_of_Mätzlingen_gradient)" inkscape:label="Mätzlingen" aria-label="MÄTZLINGEN" width="3" height="2"/>\n'
        '<use xlink:href="#star_of_Groß"/><use href=\'#star_of_Groß\'/>\n'
        "</svg>\n"
    )
    out = flags.strip_text_metadata(svg)
    for leak in ("Mätzlingen", "MÄTZLINGEN", "Groß", "<title", "<desc", "<metadata", "<!--", "inkscape", "sodipodi", "aria-"):
        assert leak not in out, leak
    assert 'id="i0"' in out and 'id="i1"' in out
    assert "url(#i0)" in out
    assert 'xlink:href="#i1"' in out and "href='#i1'" in out
    assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in out


def test_strip_removes_scripts_and_event_handlers():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        "<script>alert('Groß')</script><foreignObject><p>Mätzlingen</p></foreignObject>"
        '<rect width="3" height="2" onclick="x()"/></svg>'
    )
    out = flags.strip_text_metadata(svg)
    for leak in ("script", "onload", "onclick", "foreignObject", "alert"):
        assert leak not in out, leak
    assert '<rect width="3" height="2"/>' in out


def test_download_only_from_commons(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        flags.download("https://example.com/Flag.svg", "0" * 40, cache=tmp_path)
    with pytest.raises(ValueError):
        flags.download(flags.UPLOAD_PREFIX + "a/ab/F.svg", "../../etc", cache=tmp_path)


def _fake_env(tmp_path: Path, licenses: dict[str, str]):
    """imageinfo + download fakes over in-memory SVGs, no network."""
    blobs = {f: f'<svg xmlns="http://www.w3.org/2000/svg"><title>{f}</title><rect width="3" height="2"/></svg>'.encode() for f in licenses}

    def imageinfo(files):
        return {
            f: {
                "title": f,
                "license": licenses[f],
                "license_template": None,
                "url": f"{flags.UPLOAD_PREFIX}x/xy/{f}",
                "page": f"https://commons.example.org/wiki/{f}",
                "sha1": hashlib.sha1(blobs[f]).hexdigest(),
                "size": len(blobs[f]),
            }
            for f in files
        }

    def download(url, sha1):
        name = url.rsplit("/", 1)[-1]
        target = tmp_path / f"{sha1}.svg"
        target.write_bytes(blobs[name])
        return target

    return imageinfo, download


ENTRIES = {
    "001": {"id": "001", "wikidata": "Q1", "name": {"en": "Mätzlingen"}},
    "002": {"id": "002", "wikidata": "Q2", "name": {"en": "Groß-Übersee"}, "dependency_of": "001"},
}


def test_build_passes_pd_and_documents_shared_flags(tmp_path):
    p41 = {
        "Q1": [{"file": "Flag of Mätzlingen.svg", "rank": "preferred", "start": None, "end": None}],
        "Q2": [{"file": "Flag of Mätzlingen.svg", "rank": "normal", "start": None, "end": None}],
    }
    imageinfo, download = _fake_env(tmp_path, {"Flag of Mätzlingen.svg": "Public domain"})
    manifest, problems = flags.build(ENTRIES, p41, {}, imageinfo, download, media=tmp_path / "media")
    assert problems == []
    assert manifest["002"]["shared_with"] == "001"
    out = (tmp_path / "media" / "cotw-001-flag.svg").read_text(encoding="utf-8")
    assert "<title" not in out and "Mätzlingen" not in out


def test_build_fails_on_foreign_license_unless_overridden(tmp_path):
    p41 = {
        "Q1": [{"file": "Flag A.svg", "rank": "preferred", "start": None, "end": None}],
        "Q2": [{"file": "Flag B.svg", "rank": "preferred", "start": None, "end": None}],
    }
    imageinfo, download = _fake_env(tmp_path, {"Flag A.svg": "Public domain", "Flag B.svg": "CC BY-SA 4.0"})
    _, problems = flags.build(ENTRIES, p41, {}, imageinfo, download, media=tmp_path / "media")
    assert len(problems) == 1 and "CC BY-SA 4.0" in problems[0]
    assert not (tmp_path / "media").exists(), "nothing is written when a license fails"

    overrides = {"002": {"license": "CC BY-SA 4.0", "reason": "Test: accepted by Jürgen Groß"}}
    manifest, problems = flags.build(ENTRIES, p41, overrides, imageinfo, download, media=tmp_path / "media")
    assert problems == []
    assert manifest["002"]["license_override"].startswith("Test")


def test_build_file_override_replaces_p41(tmp_path):
    p41 = {"Q1": [], "Q2": [{"file": "Flag B.svg", "rank": "preferred", "start": None, "end": None}]}
    imageinfo, download = _fake_env(tmp_path, {"Flag A.svg": "CC0", "Flag B.svg": "Public domain"})
    overrides = {"001": {"file": "Flag A.svg", "reason": "no P41"}}
    manifest, problems = flags.build(ENTRIES, p41, overrides, imageinfo, download, media=tmp_path / "media")
    assert problems == []
    assert manifest["001"]["file"] == "Flag A.svg"
    assert manifest["001"]["selection"].startswith("override")
