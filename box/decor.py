#!/usr/bin/env python3
"""
Engraved decoration for the front panel: a monoline italic script and a few
birds, both as explicit Bezier paths.

Why paths and not <text>
------------------------
A laser front-end renders <text> with whatever font it happens to have, and
most of them silently substitute one. A title that reads "La boite a piafs"
in Arial on the cutter is not what was designed. Every glyph here is drawn
from control points, so the file carries its own lettering and cuts the same
everywhere. It also engraves as a single-line (centre-line) stroke, which is
what a vector engrave actually does well -- an outlined font would need fill.

Glyph space
-----------
y is UP, baseline y = 0, x-height = 1.0, ascenders ~1.9, descenders ~-0.7.
Slant is applied at layout time (x += SLANT * y), so glyph stems are drawn
vertical and the whole hand leans together.

Each glyph carries `entry` and `exit` points, both on the ink. Consecutive
glyphs are linked by a generated cubic, which is what makes the line read as
handwriting rather than as letters standing next to each other.
"""

from __future__ import annotations

SLANT = 0.20          # ~11 degrees
ASC = 1.9
DESC = -0.75


def _c(*pts):
    """A stroke: first point, then (c1, c2, end) triples."""
    return list(pts)


# ---------------------------------------------------------------------
#  glyphs (only the letters the panel titles need)
# ---------------------------------------------------------------------
GLYPHS = {
    " ": dict(adv=0.45, entry=None, exit=None, strokes=[]),

    "L": dict(
        adv=1.00, entry=(0.40, 1.60), exit=(0.92, 0.05),
        strokes=[_c((0.58, 1.90),
                    ((0.34, 1.96), (0.16, 1.72), (0.30, 1.46)),
                    ((0.44, 1.18), (0.20, 0.52), (0.15, 0.20)),
                    ((0.12, 0.02), (0.30, -0.07), (0.50, 0.02)),
                    ((0.66, 0.09), (0.80, 0.11), (0.92, 0.05)))],
    ),

    "a": dict(
        adv=0.80, entry=(0.10, 0.82), exit=(0.86, 0.14),
        strokes=[
            _c((0.66, 0.96),                                   # bowl
               ((0.48, 1.06), (0.06, 1.00), (0.06, 0.56)),
               ((0.06, 0.14), (0.40, -0.06), (0.66, 0.16))),
            _c((0.66, 1.00),                                   # stem + flick
               ((0.66, 0.70), (0.63, 0.35), (0.66, 0.10)),
               ((0.68, -0.02), (0.78, 0.02), (0.86, 0.14))),
        ],
    ),

    "b": dict(
        adv=0.78, entry=(0.18, 0.40), exit=(0.72, 0.60),
        strokes=[
            _c((0.34, 1.88),                                   # ascender
               ((0.30, 1.30), (0.20, 0.70), (0.18, 0.10))),
            _c((0.18, 0.12),                                   # bowl
               ((0.34, -0.06), (0.68, 0.04), (0.71, 0.34)),
               ((0.74, 0.66), (0.50, 0.92), (0.25, 0.86))),
        ],
    ),

    "o": dict(
        adv=0.76, entry=(0.10, 0.80), exit=(0.80, 0.80),
        strokes=[_c((0.62, 0.70),
                    ((0.64, 0.98), (0.30, 1.10), (0.12, 0.86)),
                    ((-0.01, 0.64), (0.01, 0.24), (0.22, 0.08)),
                    ((0.44, -0.07), (0.68, 0.14), (0.65, 0.44)),
                    ((0.63, 0.62), (0.60, 0.70), (0.63, 0.78)),
                    ((0.67, 0.90), (0.74, 0.90), (0.80, 0.80)))],
    ),

    "i": dict(
        adv=0.44, entry=(0.15, 0.98), exit=(0.40, 0.14),
        strokes=[
            _c((0.15, 1.00),
               ((0.14, 0.70), (0.10, 0.32), (0.12, 0.10)),
               ((0.16, -0.02), (0.28, 0.00), (0.40, 0.14))),
            _c((0.13, 1.30),                                   # dot
               ((0.20, 1.30), (0.22, 1.42), (0.15, 1.42)),
               ((0.08, 1.42), (0.06, 1.30), (0.13, 1.30))),
        ],
    ),

    "t": dict(
        adv=0.58, entry=(0.27, 0.96), exit=(0.55, 0.14),
        strokes=[
            _c((0.31, 1.34),
               ((0.29, 0.92), (0.24, 0.38), (0.26, 0.12)),
               ((0.30, -0.02), (0.42, 0.00), (0.55, 0.14))),
            _c((0.00, 0.92),                                   # crossbar
               ((0.18, 1.02), (0.42, 1.02), (0.60, 0.94))),
        ],
    ),

    "e": dict(
        adv=0.72, entry=(0.06, 0.46), exit=(0.72, 0.18),
        strokes=[_c((0.06, 0.46),
                    ((0.22, 0.55), (0.44, 0.58), (0.60, 0.54)),
                    ((0.70, 0.90), (0.32, 1.14), (0.12, 0.84)),
                    ((0.00, 0.62), (0.02, 0.22), (0.24, 0.08)),
                    ((0.44, -0.03), (0.62, 0.04), (0.72, 0.18)))],
    ),

    "p": dict(
        adv=0.78, entry=(0.25, 0.98), exit=(0.64, 0.12),
        strokes=[
            _c((0.25, 1.02),                                   # stem + tail
               ((0.22, 0.55), (0.14, 0.05), (0.10, -0.58)),
               ((0.08, -0.70), (0.15, -0.76), (0.24, -0.68))),
            _c((0.23, 0.90),                                   # bowl
               ((0.44, 1.06), (0.74, 0.90), (0.72, 0.55)),
               ((0.70, 0.22), (0.40, 0.02), (0.17, 0.18))),
        ],
    ),

    "f": dict(
        adv=0.62, entry=(0.26, 0.96), exit=(0.20, 0.06),
        strokes=[
            _c((0.62, 1.58),                                   # head hook
               ((0.60, 1.90), (0.30, 1.96), (0.29, 1.52)),
               ((0.27, 1.00), (0.21, 0.40), (0.16, -0.26)),     # long stem
               ((0.13, -0.56), (-0.02, -0.62), (-0.10, -0.46))),
            _c((0.02, 0.92),                                   # crossbar
               ((0.18, 1.01), (0.38, 1.01), (0.54, 0.94))),
        ],
    ),

    "s": dict(
        adv=0.60, entry=(0.10, 0.84), exit=(0.16, 0.06),
        strokes=[_c((0.54, 0.86),
                    ((0.48, 1.06), (0.12, 1.10), (0.10, 0.84)),
                    ((0.08, 0.64), (0.34, 0.56), (0.44, 0.44)),
                    ((0.56, 0.28), (0.50, 0.02), (0.26, 0.04)),
                    ((0.20, 0.05), (0.17, 0.05), (0.16, 0.06)))],
    ),
}

# Accents ride above a base letter; kept apart so "i"/"a" stay single glyphs.
ACCENTS = {
    "^": _c((-0.02, 1.32), ((0.06, 1.44), (0.10, 1.52), (0.16, 1.56)),
            ((0.22, 1.52), (0.26, 1.44), (0.34, 1.32))),
    "`": _c((0.10, 1.56), ((0.16, 1.48), (0.22, 1.40), (0.30, 1.32))),
}

# An accented letter loses its own tittle: "î" is a circumflex over a
# dotless i, not a circumflex over a dotted one.
COMPOSED = {"î": ("i", "^", 0.00), "à": ("a", "`", 0.14)}
DOTLESS = {"i"}


# ---------------------------------------------------------------------
#  layout
# ---------------------------------------------------------------------
def _join(a, b):
    """
    Cubic linking one glyph's exit to the next one's entry.

    An italic join is a near-straight diagonal with a slight sag, not a
    flourish: control points sit along the chord and are pushed a little
    below it. Earlier versions offset them vertically by a fixed amount,
    which put a visible hump-then-dip in every join.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    sag = 0.10 * max(0.2, abs(dx))
    c1 = (a[0] + 0.35 * dx, a[1] + 0.35 * dy - sag)
    c2 = (b[0] - 0.35 * dx, b[1] - 0.35 * dy - sag)
    return [a, (c1, c2, b)]


def supported() -> str:
    """Every character the hand can set, for a clear error on the rest."""
    return "".join(sorted(set(GLYPHS) | set(COMPOSED)))


def script_strokes(s: str, gap: float = 0.16):
    """Strokes for `s` in glyph units, with joins. Returns (strokes, width)."""
    missing = sorted(set(s) - set(GLYPHS) - set(COMPOSED))
    if missing:
        raise KeyError(f"no glyph drawn for {missing}; this hand has "
                       f"{supported()!r} -- add it to GLYPHS")
    strokes, pen, prev_exit = [], 0.0, None
    for ch in s:
        base, acc, acc_dx = COMPOSED.get(ch, (ch, None, 0.0))
        g = GLYPHS[base]
        glyph_strokes = g["strokes"]
        if acc and base in DOTLESS:
            glyph_strokes = glyph_strokes[:1]
        if prev_exit is not None and g["entry"] is not None:
            entry = (g["entry"][0] + pen, g["entry"][1])
            strokes.append(_join(prev_exit, entry))
        for st in glyph_strokes:
            strokes.append(_shift(st, pen))
        if acc:
            strokes.append(_shift(ACCENTS[acc], pen + acc_dx))
        prev_exit = ((g["exit"][0] + pen, g["exit"][1]) if g["exit"] else None)
        pen += g["adv"] + gap
    return strokes, pen - gap


def _shift(stroke, dx):
    out = [(stroke[0][0] + dx, stroke[0][1])]
    for seg in stroke[1:]:
        out.append(tuple((px + dx, py) for px, py in seg))
    return out


def _place(stroke, scale, ox, oy, slant):
    """Glyph units -> panel mm. Applies slant, scales, flips y (SVG is y-down)."""
    def f(pt):
        x, y = pt
        return (ox + (x + slant * y) * scale, oy - y * scale)
    out = [f(stroke[0])]
    for seg in stroke[1:]:
        out.append(tuple(f(p) for p in seg))
    return out


def _d(stroke):
    d = f"M {stroke[0][0]:.2f},{stroke[0][1]:.2f}"
    for c1, c2, p in stroke[1:]:
        d += (f" C {c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} "
              f"{p[0]:.2f},{p[1]:.2f}")
    return d


ENG = 'stroke="#0000ff" stroke-width="0.1" fill="none"'


def _fit(s, xheight, max_width, slant):
    """Scale in mm per glyph unit, shrunk if the line would overflow."""
    _, w = script_strokes(s)
    total = w + slant * ASC
    if max_width and total * xheight > max_width:
        return max_width / total, total
    return xheight, total


def script_text(s, cx, baseline, xheight, max_width=None, style=ENG,
                slant=SLANT):
    """
    Engraved script centred on cx, sitting on `baseline` (panel mm, y down).

    `xheight` is the height of an 'o'; capitals and ascenders run to ~1.9x
    that and descenders to ~0.75x below. If max_width is given the whole line
    is scaled down to fit rather than overflowing the panel.
    """
    strokes, _ = script_strokes(s)
    scale, total = _fit(s, xheight, max_width, slant)
    ox = cx - total * scale / 2
    return [f'<path d="{_d(_place(st, scale, ox, baseline, slant))}" {style}/>'
            for st in strokes]


def script_extent(s, xheight, max_width=None, slant=SLANT):
    """(width, height above baseline, depth below) in mm, for layout checks."""
    scale, total = _fit(s, xheight, max_width, slant)
    return total * scale, ASC * scale, -DESC * scale


# ---------------------------------------------------------------------
#  birds
# ---------------------------------------------------------------------
# Drawn in a unit box: x 0..1 to the right, y 0..1 UP from the box floor,
# so a motif is placed by its bottom-left corner and sized by one number.
# Engraved as outlines, which a vector engrave traces as a line drawing --
# the same reason the lettering is monoline.

_PERCHED = [
    # body: beak, over the head, down the back, tail, belly, back to the beak
    _c((0.84, 0.76),
       ((0.90, 0.90), (0.76, 0.98), (0.63, 0.90)),
       ((0.48, 0.80), (0.34, 0.64), (0.26, 0.48)),
       ((0.20, 0.42), (0.10, 0.35), (-0.04, 0.25)),            # upper tail
       ((0.05, 0.23), (0.16, 0.21), (0.28, 0.20)),             # lower tail
       ((0.44, 0.13), (0.61, 0.24), (0.72, 0.43)),             # belly
       ((0.77, 0.55), (0.81, 0.66), (0.84, 0.76))),
    # beak
    _c((0.83, 0.81), ((0.91, 0.81), (0.98, 0.80), (1.05, 0.78)),
       ((0.98, 0.75), (0.91, 0.73), (0.84, 0.72))),
    # wing
    _c((0.58, 0.62),
       ((0.48, 0.70), (0.32, 0.62), (0.25, 0.45)),
       ((0.37, 0.37), (0.52, 0.45), (0.58, 0.62))),
    # eye
    _c((0.73, 0.83), ((0.77, 0.83), (0.78, 0.89), (0.74, 0.89)),
       ((0.70, 0.89), (0.69, 0.83), (0.73, 0.83))),
    # legs, reaching the motif floor so the bird stands on the branch
    _c((0.50, 0.22), ((0.51, 0.14), (0.49, 0.07), (0.46, 0.00))),
    _c((0.62, 0.26), ((0.64, 0.16), (0.63, 0.08), (0.61, 0.00))),
]

_FLYING = [
    # one continuous silhouette: left wingtip, over the body, right wingtip
    _c((0.00, 0.72),
       ((0.14, 0.72), (0.30, 0.60), (0.40, 0.42)),             # leading edge
       ((0.44, 0.34), (0.52, 0.32), (0.58, 0.40)),             # body notch
       ((0.68, 0.56), (0.84, 0.70), (1.00, 0.70)),
       ((0.86, 0.58), (0.72, 0.46), (0.60, 0.28)),             # trailing edge
       ((0.54, 0.19), (0.44, 0.19), (0.38, 0.28)),
       ((0.26, 0.46), (0.14, 0.62), (0.00, 0.72))),
]

_SWALLOW = [
    # a plainer two-stroke bird for the small sizes, where an outline closes up
    _c((0.00, 0.60), ((0.16, 0.66), (0.34, 0.60), (0.46, 0.36))),
    _c((0.46, 0.36), ((0.58, 0.60), (0.76, 0.66), (0.94, 0.58))),
]

# The twig's main stroke runs along v = 0, the same floor the perched bird's
# feet stand on, so the two motifs share one y and the bird is not left
# hovering above its perch.
_BRANCH = [
    _c((0.00, 0.06), ((0.30, -0.04), (0.68, -0.04), (1.00, 0.05))),
    _c((0.12, 0.01), ((0.15, 0.12), (0.11, 0.22), (0.02, 0.28)),   # leaf
       ((0.07, 0.16), (0.09, 0.08), (0.12, 0.01))),
    _c((0.84, 0.00), ((0.88, 0.11), (0.95, 0.19), (1.06, 0.23)),   # leaf
       ((0.98, 0.13), (0.90, 0.06), (0.84, 0.00))),
]


def _norm(strokes):
    """
    Rescale a motif so its ink spans exactly u = 0..1, floor at v = 0.

    The control points are drawn by eye and stray outside the nominal box --
    a beak at 1.05, a leaf at -0.04. Without this, `w` would be a rough hint
    rather than the motif's real width, and placing a bird one millimetre
    clear of the display pocket would still let its tail cross the line.
    """
    xs = [p[0] for st in strokes for pt in st
          for p in (pt if isinstance(pt[0], tuple) else (pt,))]
    lo, hi = min(xs), max(xs)
    s = 1.0 / (hi - lo)

    def f(pt):
        return ((pt[0] - lo) * s, pt[1] * s)
    out = []
    for st in strokes:
        out.append([f(st[0])] + [tuple(f(p) for p in seg) for seg in st[1:]])
    return out


_NORM_CACHE: dict[int, list] = {}


def _motif(strokes, x, y, w, flip=False, style=ENG):
    """Place a unit-box motif with its bottom-left at (x, y), width w."""
    key = id(strokes)
    if key not in _NORM_CACHE:
        _NORM_CACHE[key] = _norm(strokes)

    def f(pt):
        u, v = pt
        return (x + (1.0 - u) * w if flip else x + u * w, y - v * w)
    out = []
    for st in _NORM_CACHE[key]:
        pl = [f(st[0])] + [tuple(f(p) for p in seg) for seg in st[1:]]
        out.append(f'<path d="{_d(pl)}" {style}/>')
    return out


def bird_perched(x, y, w, flip=False, style=ENG):
    """Songbird sitting on the baseline y, facing right (left if flipped)."""
    return _motif(_PERCHED, x, y, w, flip, style)


def bird_flying(x, y, w, flip=False, style=ENG):
    """Bird in flight, wings raised."""
    return _motif(_FLYING, x, y, w, flip, style)


def bird_swallow(x, y, w, flip=False, style=ENG):
    """Distant bird: two strokes, legible down to a few millimetres."""
    return _motif(_SWALLOW, x, y, w, flip, style)


def branch(x, y, w, flip=False, style=ENG):
    """Twig with two leaves, for a perched bird to stand on."""
    return _motif(_BRANCH, x, y, w, flip, style)


# ---------------------------------------------------------------------
#  flattening, for clearance checks
# ---------------------------------------------------------------------
def flatten(elements, steps: int = 16):
    """Every emitted path as a polyline of (x, y) points, in panel mm."""
    import re
    pts = []
    for el in elements:
        m = re.search(r'\sd="([^"]+)"', el)
        if not m:
            continue
        nums = re.findall(r'[-+]?\d*\.?\d+', m.group(1))
        cmds = re.findall(r'[MC]', m.group(1))
        i, pos = 0, None
        for c in cmds:
            if c == "M":
                pos = (float(nums[i]), float(nums[i + 1]))
                i += 2
                pts.append(pos)
            else:
                p1 = (float(nums[i]), float(nums[i + 1]))
                p2 = (float(nums[i + 2]), float(nums[i + 3]))
                p3 = (float(nums[i + 4]), float(nums[i + 5]))
                i += 6
                for k in range(1, steps + 1):
                    tt = k / steps
                    u = 1 - tt
                    pts.append((u*u*u*pos[0] + 3*u*u*tt*p1[0]
                                + 3*u*tt*tt*p2[0] + tt*tt*tt*p3[0],
                                u*u*u*pos[1] + 3*u*u*tt*p1[1]
                                + 3*u*tt*tt*p2[1] + tt*tt*tt*p3[1]))
                pos = p3
    return pts
