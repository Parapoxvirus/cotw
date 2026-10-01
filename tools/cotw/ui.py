"""Template assets for the card UI, one file per mode (roadmap step 4, issue #12).

``python -m cotw build-ui`` writes ``media/ui/`` (committed, generated, never edited by hand):

* ``_cotw-ui-<icon>-day.svg`` / ``-night.svg``: the Phosphor row icons of ``assets/ui/``
  in the card's text color per mode (the originals are white).
* ``_cotw-ui-infographic[-filtered]-day.svg`` / ``-night.svg``: the two help-section
  infographics, rebuilt as SVG from the same Phosphor icons (verbatim path data, placed and
  scaled to the positions measured on the v3 PNGs), two curly braces and the center square,
  on a transparent background. The v3 PNGs had an opaque beige background and black lines
  that vanished in night mode; their design file no longer exists.

``fidelity()`` rasterizes an infographic at the PNG's size and compares it with the PNG
(line-mask IoU and maximum deviation in pixels); ``tests/test_ui.py`` holds it to the
tolerance in docs/DECK.md. Rasterizing needs shapely and Pillow; writing the SVGs does not.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from .paths import MEDIA, UI_ASSETS

UI_SOURCE = UI_ASSETS
UI_MEDIA = MEDIA / "ui"
MODES = ("day", "night")

# Text color per mode (docs/DECK.md): the row icons follow it.
TEXT = {"day": "#1F2328", "night": "#E6EDF3"}
# Infographic line colors; "gray" marks the extras in the filtered variant.
INFOGRAPHIC_COLORS = {"day": {"line": "#1F2328", "gray": "#C9CDD1"}, "night": {"line": "#E6EDF3", "gray": "#5A5F66"}}

# Row icons: logical name → Phosphor source file (regular weight, 256 × 256, white fill).
ICONS = {
    "country": "_cotw-ui-country.svg",
    "formal": "_cotw-ui-longform.svg",
    "capital": "_cotw-ui-capital.svg",
    "iso": "_cotw-ui-iso.svg",
    "flag": "_cotw-ui-flag.svg",
    "borders": "_cotw-ui-borders.svg",
    "map": "_cotw-ui-map.svg",
    "info": "_cotw-ui-info.svg",
    "help": "_cotw-ui-help.svg",
}


def icon_path(name: str) -> str:
    """The ``d`` attribute of a Phosphor icon, verbatim."""
    text = (UI_SOURCE / ICONS[name]).read_text(encoding="utf-8")
    paths = re.findall(r'<path d="([^"]+)"', text)
    if len(paths) != 1:
        raise RuntimeError(f"{ICONS[name]}: expected exactly one path")
    return paths[0]


def icon_svg(name: str, color: str) -> str:
    """The icon file with its fill replaced; everything else stays as Phosphor ships it."""
    text = (UI_SOURCE / ICONS[name]).read_text(encoding="utf-8").strip()
    if text.count('fill="#ffffff"') != 1:
        raise RuntimeError(f"{ICONS[name]}: expected one white fill")
    return text.replace('fill="#ffffff"', f'fill="{color}"') + "\n"


def icon_file(name: str, mode: str) -> str:
    stem = Path(ICONS[name]).stem
    return f"{stem}-{mode}.svg"


# --- infographic layout ----------------------------------------------------------------------
#
# Measured on the 1848 × 1713 v3 PNGs (issue #12): the original was built from the same
# Phosphor icons at one scale, 1.285 (the center square is Phosphor's square, our country
# icon), on a grid of 330 px rows; offsets were fit to maximize the line-mask IoU and then
# rounded to that grid (the left map sits 5 px higher in the PNG and here too). The braces
# are cubic Béziers whose control points were fit the same way. Column "left" is the prompt
# side (X → Country), "right" the answer side (Country → X).

WIDTH, HEIGHT = 1848, 1713
ROWS = ("capital", "flag", "map", "iso", "borders")
COLUMNS = ("left", "center", "right")
ICON_SCALE = 1.285
_ROW_Y = {"capital": 37, "flag": 367, "map": 697, "iso": 1027, "borders": 1357}
# (icon, column) → (scale, translate x, translate y): user = translate + scale × icon.
ICON_PLACEMENT: dict[tuple[str, str], tuple[float, float, float]] = {
    **{(name, "left"): (ICON_SCALE, 1.0, _ROW_Y[name] - (5 if name == "map" else 0)) for name in ROWS},
    **{(name, "right"): (ICON_SCALE, 1519.0, _ROW_Y[name]) for name in ROWS},
    ("country", "center"): (ICON_SCALE, 760.0, 697.0),
}
# The two braces: stroked paths with round caps, in user units (= PNG pixels).
BRACES = {
    "left": "M436.5 36.2C487.5 36.2 518 115.2 518 209.2V687.5C518 772.3 543 862 598 862C543 862 518 951.7 518 1036.5V1514.8C518 1608.8 487.5 1687.8 436.5 1687.8",
    "right": "M1411.2 37C1361.4 37 1332 117.4 1332 211.2V687C1332 778.8 1304 862 1251.2 862C1304 862 1332 945.2 1332 1037V1512.8C1332 1606.6 1361.4 1687 1411.2 1687",
}
BRACE_STROKE = 20.0
# Extras grayed in the filtered variant (as in the v3 PNG): the ISO code and bordering
# countries in both directions, and Country → Map (right column). Map → Country (left) is a
# recommended card type and stays black.
GRAYED = {("iso", "left"), ("borders", "left"), ("map", "right"), ("iso", "right"), ("borders", "right")}


def _num(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def _order(item) -> tuple[int, int]:
    (name, col), _ = item
    return COLUMNS.index(col), ROWS.index(name) if name in ROWS else 0


def infographic_svg(filtered: bool, mode: str) -> str:
    """One infographic, transparent background, lines in the mode's colors."""
    colors = INFOGRAPHIC_COLORS[mode]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
    ]
    for (name, col), (s, tx, ty) in sorted(ICON_PLACEMENT.items(), key=_order):
        color = colors["gray"] if filtered and (name, col) in GRAYED else colors["line"]
        out.append(
            f'<path fill="{color}" transform="translate({_num(tx)} {_num(ty)}) scale({_num(s)})" d="{icon_path(name)}"/>'
        )
    line = colors["line"]
    stroke = f'fill="none" stroke="{line}" stroke-width="{_num(BRACE_STROKE)}" stroke-linecap="round" stroke-linejoin="round"'
    for side in ("left", "right"):
        out.append(f'<path {stroke} d="{BRACES[side]}"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def infographic_file(filtered: bool, mode: str) -> str:
    return f"_cotw-ui-infographic{'-filtered' if filtered else ''}-{mode}.svg"


def files() -> dict[str, str]:
    """Every generated file: name → content."""
    out = {}
    for name in ICONS:
        for mode in MODES:
            out[icon_file(name, mode)] = icon_svg(name, TEXT[mode])
    for filtered in (False, True):
        for mode in MODES:
            out[infographic_file(filtered, mode)] = infographic_svg(filtered, mode)
    return dict(sorted(out.items()))


def build(target: Path = UI_MEDIA) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, text in files().items():
        path = target / name
        path.write_text(text, encoding="utf-8")
        written.append(path)
    for stale in sorted(target.glob("*.svg")):
        if stale.name not in files():
            stale.unlink()
    return written


# --- SVG path geometry (for the fidelity check) ------------------------------------------------

_TOKEN = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


def _arc(x1, y1, rx, ry, phi, large, sweep, x2, y2, steps_per_rad=16):
    """Endpoint arc → points (SVG 1.1 implementation notes F.6.5), excluding the start."""
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    rx, ry = abs(rx), abs(ry)
    cp, sp = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (x1 - x2) / 2.0, (y1 - y2) / 2.0
    xp, yp = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (xp * xp) / (rx * rx) + (yp * yp) / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp
    den = rx * rx * yp * yp + ry * ry * xp * xp
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * yp / ry, -co * ry * xp / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2.0
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2.0

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a

    t1 = ang(1, 0, (xp - cxp) / rx, (yp - cyp) / ry)
    dt = ang((xp - cxp) / rx, (yp - cyp) / ry, (-xp - cxp) / rx, (-yp - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(2, int(abs(dt) * steps_per_rad))
    pts = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cp * x - sp * y + cx, sp * x + cp * y + cy))
    pts[-1] = (x2, y2)
    return pts


def _cubic(p0, p1, p2, p3, n=24):
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t**3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def flatten(d: str) -> list[tuple[list[tuple[float, float]], bool]]:
    """Path data → ``[(points, closed)]`` per subpath (curves and arcs as polylines)."""
    tokens = _TOKEN.findall(d)
    subpaths: list[tuple[list, bool]] = []
    pts: list[tuple[float, float]] = []
    x = y = sx = sy = 0.0
    last_ctrl = None
    cmd = None
    i = 0

    def flush(closed):
        nonlocal pts
        if len(pts) > 1:
            subpaths.append((pts, closed))
        pts = []

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                flush(True)
                x, y = sx, sy
                last_ctrl = None
                continue
        up, rel = cmd.upper(), cmd.islower()
        n = _ARGS[up]
        args = [float(t) for t in tokens[i : i + n]]
        i += n
        ox, oy = (x, y) if rel else (0.0, 0.0)
        ctrl = None
        if up == "M":
            flush(False)
            x, y = ox + args[0], oy + args[1]
            sx, sy = x, y
            pts = [(x, y)]
            cmd = "l" if rel else "L"  # further pairs are line-tos
        elif up == "L":
            x, y = ox + args[0], oy + args[1]
            pts.append((x, y))
        elif up == "H":
            x = (x if rel else 0.0) + args[0]
            pts.append((x, y))
        elif up == "V":
            y = (y if rel else 0.0) + args[0]
            pts.append((x, y))
        elif up in "CS":
            if up == "C":
                c1 = (ox + args[0], oy + args[1])
                c2, end = (ox + args[2], oy + args[3]), (ox + args[4], oy + args[5])
            else:
                c1 = (2 * x - last_ctrl[0], 2 * y - last_ctrl[1]) if last_ctrl else (x, y)
                c2, end = (ox + args[0], oy + args[1]), (ox + args[2], oy + args[3])
            pts += _cubic((x, y), c1, c2, end)
            ctrl = c2
            x, y = end
        elif up == "Q":
            q, end = (ox + args[0], oy + args[1]), (ox + args[2], oy + args[3])
            c1 = (x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y))
            c2 = (end[0] + 2 / 3 * (q[0] - end[0]), end[1] + 2 / 3 * (q[1] - end[1]))
            pts += _cubic((x, y), c1, c2, end)
            x, y = end
        elif up == "A":
            end = (ox + args[5], oy + args[6])
            pts += _arc(x, y, args[0], args[1], args[2], int(args[3]), int(args[4]), *end)
            x, y = end
        else:
            raise ValueError(f"unsupported path command {cmd!r}")
        last_ctrl = ctrl
    flush(False)
    return subpaths


def fill_geometry(d: str, transform=(1.0, 0.0, 0.0)):
    """Filled path → shapely geometry (even-odd; Phosphor's holes are counter-wound rings,
    so even-odd and nonzero agree). ``transform`` = (scale, tx, ty)."""
    import shapely
    from shapely.geometry import Polygon

    s, tx, ty = transform
    geom = None
    for pts, _closed in flatten(d):
        ring = [(tx + s * px, ty + s * py) for px, py in pts]
        if len(ring) < 3:
            continue
        poly = shapely.make_valid(Polygon(ring))
        geom = poly if geom is None else geom.symmetric_difference(poly)
    return geom


def stroke_geometry(d: str, width: float):
    """Stroked path with round caps and joins → shapely geometry."""
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    parts = []
    for pts, closed in flatten(d):
        line = LineString(pts + ([pts[0]] if closed else []))
        parts.append(line.buffer(width / 2.0, quad_segs=16, cap_style="round", join_style="round"))
    return unary_union(parts)


def infographic_geometry(filtered: bool) -> dict[str, object]:
    """``{"line": geom, "gray": geom}`` of one infographic in user units (= PNG pixels)."""
    from shapely.ops import unary_union

    line, gray = [], []
    for (name, col), t in ICON_PLACEMENT.items():
        g = fill_geometry(icon_path(name), t)
        (gray if filtered and (name, col) in GRAYED else line).append(g)
    for side in ("left", "right"):
        line.append(stroke_geometry(BRACES[side], BRACE_STROKE))
    return {"line": unary_union(line), "gray": unary_union(gray) if gray else None}


def rasterize(geom, size=(WIDTH, HEIGHT)):
    """Shapely geometry → boolean mask (pixel centers inside, no anti-aliasing)."""
    import numpy as np
    from PIL import Image, ImageDraw

    from .geometry import polygons

    img = Image.new("1", size, 0)
    draw = ImageDraw.Draw(img)
    for p in sorted(polygons(geom), key=lambda q: -q.area):
        draw.polygon([(x - 0.5, y - 0.5) for x, y in p.exterior.coords], fill=1)
        for ring in p.interiors:
            draw.polygon([(x - 0.5, y - 0.5) for x, y in ring.coords], fill=0)
    return np.asarray(img, dtype=bool)


def png_masks(filtered: bool) -> dict[str, object]:
    """Line masks of the v3 PNG: ``line`` (black, below mid-gray against the beige) and
    ``gray`` (the grayed extras: below the midpoint between their gray and the beige)."""
    import numpy as np
    from PIL import Image

    name = f"_cotw-ui-infographic{'-filtered' if filtered else ''}.png"
    lum = np.asarray(Image.open(UI_SOURCE / name).convert("L"), dtype=float)
    bg = float(np.median(lum))
    black = lum < bg / 2.0
    out = {"line": black, "gray": None}
    if filtered:
        # The gray lines: the darkest pixel that is not black anti-aliasing, midway to the bg.
        gray_level = 209.0
        out["gray"] = (lum < (gray_level + bg) / 2.0) & ~_dilate(black, 2)
    return out


def _dilate(mask, k: int):
    import numpy as np

    out = mask.copy()
    for _ in range(k):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def max_deviation(a, b, limit: int = 40) -> int:
    """Smallest k such that each mask lies within k pixels (4-neighborhood) of the other."""
    for k in range(limit + 1):
        if not (a & ~_dilate(b, k)).any() and not (b & ~_dilate(a, k)).any():
            return k
    return limit + 1


def iou(a, b) -> float:
    union = (a | b).sum()
    return float((a & b).sum() / union) if union else 1.0


def fidelity(filtered: bool) -> dict[str, float]:
    """SVG vs. PNG: IoU and maximum deviation of the line masks (all lines; gray only)."""
    geom = infographic_geometry(filtered)
    png = png_masks(filtered)
    svg_line = rasterize(geom["line"])
    svg_all = svg_line | (rasterize(geom["gray"]) if geom["gray"] is not None else False)
    png_all = png["line"] | (png["gray"] if png["gray"] is not None else False)
    out = {
        "iou": iou(svg_all, png_all),
        "max_px": max_deviation(svg_all, png_all),
        "iou_black": iou(svg_line, png["line"]),
    }
    if filtered:
        out["iou_gray"] = iou(rasterize(geom["gray"]), png["gray"])
    return out


def overlay(filtered: bool, target: Path) -> Path:
    """PNG lines in magenta, SVG lines in green, both in black (for the PR / review)."""
    import numpy as np
    from PIL import Image

    geom = infographic_geometry(filtered)
    png = png_masks(filtered)
    svg = rasterize(geom["line"]) | (rasterize(geom["gray"]) if geom["gray"] is not None else False)
    ref = png["line"] | (png["gray"] if png["gray"] is not None else False)
    img = np.full((HEIGHT, WIDTH, 3), 255, dtype=np.uint8)
    img[ref & ~svg] = (230, 0, 160)
    img[svg & ~ref] = (0, 170, 60)
    img[svg & ref] = (0, 0, 0)
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img).save(target)
    return target
