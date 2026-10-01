"""UI template assets (tools/cotw/ui.py): mode-colored row icons and the SVG rebuild of the
v3 infographics, held against the original PNGs."""

from __future__ import annotations

import re

import pytest

from cotw import ui

# docs/DECK.md: the SVG rebuild of the infographics matches the v3 PNGs at their full size
# (1848 × 1713) to at least this line-mask IoU, and no line is farther off than this.
MIN_IOU = 0.96
MAX_DEVIATION_PX = 8


def test_committed_files_are_generated():
    expected = ui.files()
    committed = {p.name: p.read_text(encoding="utf-8") for p in sorted(ui.UI_MEDIA.glob("*.svg"))}
    assert sorted(committed) == sorted(expected), "run `python -m cotw build-ui`"
    for name, text in expected.items():
        assert committed[name] == text, f"{name} is stale: run `python -m cotw build-ui`"


def test_four_infographic_variants():
    names = {ui.infographic_file(f, m) for f in (False, True) for m in ui.MODES}
    assert names == {
        "_cotw-ui-infographic-day.svg",
        "_cotw-ui-infographic-night.svg",
        "_cotw-ui-infographic-filtered-day.svg",
        "_cotw-ui-infographic-filtered-night.svg",
    }
    for name in names:
        assert (ui.UI_MEDIA / name).exists(), name


@pytest.mark.parametrize("filtered", [False, True])
@pytest.mark.parametrize("mode", ui.MODES)
def test_infographic_is_transparent_in_the_mode_colors(filtered, mode):
    svg = ui.infographic_svg(filtered, mode)
    colors = ui.INFOGRAPHIC_COLORS[mode]
    # No background: nothing but the icon fills and the brace strokes.
    assert "<rect" not in svg and "background" not in svg
    assert re.search(r"<svg[^>]*\sfill=", svg) is None and re.search(r"<svg[^>]*style=", svg) is None
    used = set(re.findall(r'(?:fill|stroke)="(#[0-9A-F]{6})"', svg))
    assert used == ({colors["line"], colors["gray"]} if filtered else {colors["line"]})
    assert svg.count(f'fill="{colors["gray"]}"') == (len(ui.GRAYED) if filtered else 0)


def test_infographic_uses_the_phosphor_icons_verbatim():
    svg = ui.infographic_svg(False, "day")
    for (name, _col) in ui.ICON_PLACEMENT:
        assert f'd="{ui.icon_path(name)}"' in svg
    assert svg.count("<path") == len(ui.ICON_PLACEMENT) + 2  # + the two braces


def test_grayed_extras_match_the_png():
    # Extras (docs/DECISIONS.md D): ISO code and bordering countries both ways, and
    # Country → Map, i.e. the map in the right (answer) column. Map → Country is recommended.
    assert ui.GRAYED == {("iso", "left"), ("borders", "left"), ("map", "right"), ("iso", "right"), ("borders", "right")}


def test_row_icons_follow_the_text_color():
    for name in ui.ICONS:
        for mode in ui.MODES:
            text = ui.icon_svg(name, ui.TEXT[mode])
            assert f'fill="{ui.TEXT[mode]}"' in text and "#ffffff" not in text
            assert re.findall(r'<path d="([^"]+)"', text) == [ui.icon_path(name)]
    assert ui.TEXT == {"day": "#1F2328", "night": "#E6EDF3"}


def test_path_flattening_matches_known_shapes():
    pytest.importorskip("shapely")
    # A 10 × 10 square with a quarter-circle corner of radius 4: area = 100 - 16 + 4π.
    d = "M4 0H10V10H0V4A4 4 0 0 1 4 0Z"
    g = ui.fill_geometry(d)
    assert g.area == pytest.approx(100 - 16 + 4 * 3.141592653589793, rel=2e-3)
    # Phosphor square (country icon): outer 192² rounded by 16, minus the inner 160² hole.
    sq = ui.fill_geometry(ui.icon_path("country"))
    outer = 192**2 - (4 - 3.141592653589793) * 16**2
    assert sq.area == pytest.approx(outer - 160**2, rel=2e-3)
    # A stroked line with round caps: rectangle plus one full disc.
    line = ui.stroke_geometry("M0 0L100 0", 10)
    assert line.area == pytest.approx(100 * 10 + 3.141592653589793 * 25, rel=2e-3)


@pytest.mark.parametrize("filtered", [False, True])
def test_infographic_matches_the_v3_png(filtered):
    pytest.importorskip("shapely")
    pytest.importorskip("PIL")
    m = ui.fidelity(filtered)
    assert m["iou"] >= MIN_IOU, m
    assert m["max_px"] <= MAX_DEVIATION_PX, m
    if filtered:
        assert m["iou_gray"] >= MIN_IOU, m
