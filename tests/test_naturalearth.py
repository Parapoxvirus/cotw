"""Adjacency logic on synthetic geometry (no download, shapely required)."""

from __future__ import annotations

import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import box  # noqa: E402

from cotw.naturalearth import assign_units, compute_adjacency  # noqa: E402


def test_shared_edge_counts_point_contact_does_not():
    a = box(0, 0, 1, 1)
    b = box(1, 0, 2, 1)  # shares the edge x=1 with a
    c = box(1, 1, 2, 2)  # touches a only at the corner (1, 1)
    grouped = {"AA": [{"geom": a}], "BB": [{"geom": b}], "CC": [{"geom": c}]}
    adjacency = compute_adjacency(grouped)
    assert adjacency["AA"] == ["BB"]
    assert adjacency["BB"] == ["AA", "CC"]
    assert adjacency["CC"] == ["BB"]


def test_units_are_folded_or_ignored():
    units = [
        {"name": "Cyprus", "gu_a3": "CYP", "iso2": "CY", "geom": box(0, 0, 1, 1)},
        {"name": "Northern Cyprus", "gu_a3": "CYN", "iso2": "-99", "geom": box(1, 0, 2, 1)},
        {"name": "Bir Tawil", "gu_a3": "BRT", "iso2": "-99", "geom": box(5, 5, 6, 6)},
    ]
    grouped, ignored = assign_units(units, {"CY"})
    assert [u["name"] for u in grouped["CY"]] == ["Cyprus", "Northern Cyprus"]
    assert [u["name"] for u in ignored] == ["Bir Tawil"]
