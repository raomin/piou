#!/usr/bin/env python3
"""
Parametric laser-cut enclosure for the PiouPiou bird detector.

Material: 3 mm MDF, finger-jointed. Generates one SVG with every part nested
on a single sheet: red hairlines are CUT, blue is ENGRAVE.

Everything fit-critical is a named constant in Params below. The three worth
measuring with calipers before committing MDF are flagged VERIFY.

Joint scheme
------------
Every jointed edge is a square wave alternating between the panel's outer line
("high", material present) and an inset of one material thickness ("low").
Mating edges share a length and target segment size, so they generate the same
number of segments, and are given opposite end phases -- which makes them
exactly complementary.

Corner ownership avoids three panels fighting over the same corner cube:
  * front/back walls own every corner (all four of their edges end "high"),
  * left/right walls end "low" on their vertical edges, "high" on top/bottom,
  * top/bottom panels end "low" on all four edges, so they sit inside the walls.

Decoration
----------
The front panel carries an engraved title and a few birds, drawn as Bezier
paths in decor.py rather than as SVG <text>, so nothing depends on a font
being present wherever the sheet is cut. verify_decor() measures the result
against the window, the pocket, the button and the joints.

Kerf
----
Tabs are grown by kerf/2 at each end. A tab and its mating slot are the same
nominal segment, so growing "high" segments on both panels widens tabs and
narrows slots by the same amount; the laser then removes kerf/2 per side and
both land on nominal, giving a press fit rather than a sloppy one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import decor


# =====================================================================
#  parameters
# =====================================================================
@dataclass
class Params:
    # --- material ---
    t: float = 3.0                 # MDF thickness
    kerf: float = 0.15             # laser kerf; raise if parts are loose

    # --- outer box ---
    ow: float = 98.0               # width  (x)
    od: float = 70.0               # depth  (y)
    oh: float = 105.0              # height (z)
    finger: float = 11.0           # target finger width

    # --- Raspberry Pi 3B, lying flat on the base ---
    pi_w: float = 85.0
    pi_d: float = 56.0
    pi_hole_dx: float = 58.0       # hole spacing, long axis
    pi_hole_dy: float = 49.0       # hole spacing, short axis
    pi_hole_inset: float = 3.5     # hole centre from board edge
    pi_hole_d: float = 2.9         # M2.5 clearance

    # --- display module (measured: 42 x 41 mm outline) ---
    disp_pcb_w: float = 42.0
    disp_pcb_h: float = 41.0
    disp_act_w: float = 28.0       # visible glass
    disp_act_h: float = 32.6
    # Glass taken as vertically centred in the 41 mm board: (41 - 32.6)/2.
    # If the header sits at one end and pushes the glass off-centre, this is
    # the single number to correct.
    disp_act_off_y: float = 4.2     # active-area top, from PCB top edge
    # Was 0.4 and reported as a tight fit. MDF cuts a touch undersize and a
    # populated board has solder fillets on its edges, so give it 0.4 mm per
    # side rather than 0.2.
    disp_pocket_slack: float = 0.8
    disp_window_margin: float = 0.3
    # The 1.69in 240x280 glass has rounded corners. A near-square window
    # would leave four visible gaps where the bezel overhangs nothing, so the
    # aperture is radiused to match instead of merely deburred.
    disp_corner_r: float = 3.0
    disp_centre_z: float = 68.0    # active-area centre, from box bottom

    # --- button (VERIFY: 5 mm round; panel-mount bushings often need >5) ---
    btn_hole_d: float = 5.2
    btn_centre_z: float = 26.0

    # --- INMP441 breakout on the top panel (VERIFY) ---
    mic_pcb_w: float = 15.0
    mic_pcb_h: float = 13.0
    mic_port_d: float = 5.0        # acoustic port straight through
    mic_grille_d: float = 1.6
    mic_grille_rings: int = 1

    # --- ventilation: the Pi ran 62-67 C in free air, so this is required ---
    vent_slot_w: float = 3.0
    vent_slot_l: float = 22.0
    vent_pitch: float = 7.0

    # --- power leads from the bench supply ---
    cable_slot_w: float = 12.0
    cable_slot_h: float = 5.0
    cable_slot_z: float = 12.0
    tie_hole_d: float = 3.2

    # --- sheet layout ---
    margin: float = 8.0
    gap: float = 6.0

    # The back is the service panel: press-fit, never glued, so the Pi can
    # come out. Cutting its tabs this much undersize turns an unopenable
    # glued joint into one that pulls apart by hand.
    back_clearance: float = 0.10
    pull_slot_w: float = 26.0
    pull_slot_h: float = 7.0

    # --- engraved decoration on the front panel ---
    # The title is drawn from Bezier outlines in decor.py rather than set as
    # SVG <text>, so it does not depend on a font being installed wherever
    # the sheet is finally sent.
    title: str = "La boîte à piafs"
    title_xheight: float = 5.6       # height of an 'o'; caps run ~1.9x
    title_baseline_z: float = 9.5    # baseline, from the box bottom
    decor_inset: float = 5.5         # keep decoration off the finger joints


# =====================================================================
#  geometry helpers
# =====================================================================
def segments(length: float, target: float, ends_high: bool):
    """Odd segment count so both ends share the same phase."""
    n = max(3, int(round(length / target)))
    if n % 2 == 0:
        n += 1
    step = length / n
    return [(i * step, (i + 1) * step, (i % 2 == 0) == ends_high)
            for i in range(n)]


def _edge_points(length, target, ends_high, t, kerf, high_at, low_at, axis,
                 lo, hi):
    """
    Points along one edge.

    `axis` = 'x' walks along +x with the joint offset applied to y;
    `axis` = 'y' walks along +y with the offset applied to x.

    Two things here are load-bearing and were wrong in an earlier version:

    * Kerf growth applies only to INTERNAL tab boundaries. Growing the very
      first or last boundary pushes the edge's endpoint off the panel corner,
      which leaves a kerf/2 sliver and forces a diagonal closing segment.

    * The along-edge coordinate is clamped to [lo, hi], the positions of the
      two corners this edge actually runs between. A corner belongs to
      whichever neighbouring panel's tab fills it, so an edge whose neighbour
      owns the corner must stop one thickness short. With both ends exact and
      clamped, consecutive edges meet at an identical point and the outline
      stays strictly rectilinear -- no corner vertices need inserting.
    """
    grow = kerf / 2.0
    segs = segments(length, target, ends_high)
    n = len(segs)
    pts = []
    for i, (a, b, high) in enumerate(segs):
        s2 = a - grow if high else a + grow
        e2 = b + grow if high else b - grow
        if i == 0:
            s2 = 0.0            # exact corner, no kerf growth
        if i == n - 1:
            e2 = length         # exact corner
        s2 = min(max(s2, lo), hi)
        e2 = min(max(e2, lo), hi)
        off = high_at if high else low_at
        if axis == 'x':
            pts += [(s2, off), (e2, off)]
        else:
            pts += [(off, s2), (off, e2)]
    return pts


def _dedupe(pts):
    """Drop consecutive duplicates left by clamping a segment to a corner."""
    out = []
    for q in pts:
        if not out or abs(q[0] - out[-1][0]) > 1e-9 or abs(q[1] - out[-1][1]) > 1e-9:
            out.append(q)
    if len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-9 \
            and abs(out[0][1] - out[-1][1]) < 1e-9:
        out.pop()
    return out


def panel_outline(wp, hp, p: Params, edges: dict,
                  kerf: float | None = None) -> list[tuple[float, float]]:
    """
    Counter-clockwise outline from (0,0).

    edges maps 'b','r','t','l' to None (plain straight edge) or
    {'ends_high': bool}. Offsets are always between the outer line and an
    inset of one thickness.
    """
    t, f = p.t, p.finger
    k = p.kerf if kerf is None else kerf

    # Where each corner sits. An edge that is "high" at its ends reaches the
    # outer line and owns its corners; a "low" edge stops one thickness short
    # and the neighbour's tab fills the gap.
    def _off(spec, outer, inner):
        if not spec:
            return outer
        return outer if spec['ends_high'] else inner

    b_off = _off(edges.get('b'), 0.0, t)
    t_off = _off(edges.get('t'), hp, hp - t)
    l_off = _off(edges.get('l'), 0.0, t)
    r_off = _off(edges.get('r'), wp, wp - t)

    pts: list[tuple[float, float]] = []

    # bottom, walking +x between the left and right corners, offset in y
    if edges.get('b'):
        pts += _edge_points(wp, f, edges['b']['ends_high'], t, k, 0.0, t, 'x',
                            l_off, r_off)
    else:
        pts += [(l_off, 0.0), (r_off, 0.0)]

    # right, walking +y between the bottom and top corners, offset in x
    if edges.get('r'):
        pts += _edge_points(hp, f, edges['r']['ends_high'], t, k,
                            wp, wp - t, 'y', b_off, t_off)
    else:
        pts += [(wp, b_off), (wp, t_off)]

    # top, walking -x (generate +x then reverse), offset in y
    if edges.get('t'):
        top = _edge_points(wp, f, edges['t']['ends_high'], t, k,
                           hp, hp - t, 'x', l_off, r_off)
        pts += list(reversed(top))
    else:
        pts += [(r_off, hp), (l_off, hp)]

    # left, walking -y, offset in x
    if edges.get('l'):
        left = _edge_points(hp, f, edges['l']['ends_high'], t, k,
                            0.0, t, 'y', b_off, t_off)
        pts += list(reversed(left))
    else:
        pts += [(0.0, t_off), (0.0, b_off)]

    return _dedupe(pts)


# =====================================================================
#  SVG emission
# =====================================================================
CUT = 'stroke="#ff0000" stroke-width="0.1" fill="none"'
ENG = 'stroke="#0000ff" stroke-width="0.1" fill="none"'


@dataclass
class Sheet:
    parts: list = field(default_factory=list)

    def add(self, body: str):
        self.parts.append(body)


def poly(pts, style=CUT) -> str:
    d = " ".join(f"{x:.3f},{y:.3f}" for x, y in pts)
    return f'<polygon points="{d}" {style}/>'


def circle(cx, cy, d, style=CUT) -> str:
    return f'<circle cx="{cx:.3f}" cy="{cy:.3f}" r="{d/2:.3f}" {style}/>'


def rrect(x, y, w, h, r=1.0, style=CUT) -> str:
    r = min(r, w / 2, h / 2)
    return (f'<rect x="{x:.3f}" y="{y:.3f}" width="{w:.3f}" height="{h:.3f}" '
            f'rx="{r:.3f}" ry="{r:.3f}" {style}/>')


def text(x, y, s, size=5.0) -> str:
    return (f'<text x="{x:.3f}" y="{y:.3f}" font-family="DejaVu Sans" '
            f'font-size="{size}" fill="#0000ff" '
            f'text-anchor="middle">{s}</text>')


def vents(x0, y0, w, h, p: Params, horizontal=True) -> list[str]:
    """A centred array of rounded slots inside the given area."""
    out = []
    if horizontal:
        n = max(1, int(h // p.vent_pitch))
        span = (n - 1) * p.vent_pitch
        y = y0 + (h - span) / 2 - p.vent_slot_w / 2
        for i in range(n):
            out.append(rrect(x0 + (w - p.vent_slot_l) / 2, y + i * p.vent_pitch,
                             p.vent_slot_l, p.vent_slot_w, p.vent_slot_w / 2))
    else:
        n = max(1, int(w // p.vent_pitch))
        span = (n - 1) * p.vent_pitch
        x = x0 + (w - span) / 2 - p.vent_slot_w / 2
        for i in range(n):
            out.append(rrect(x + i * p.vent_pitch, y0 + (h - p.vent_slot_l) / 2,
                             p.vent_slot_w, p.vent_slot_l, p.vent_slot_w / 2))
    return out


# =====================================================================
#  the six walls plus the small parts
# =====================================================================
# Corner ownership, per the module docstring.
E_HI = {'ends_high': True}
E_LO = {'ends_high': False}

FRONT_EDGES = {'b': E_HI, 'r': E_HI, 't': E_HI, 'l': E_HI}
SIDE_EDGES = {'b': E_HI, 'r': E_LO, 't': E_HI, 'l': E_LO}
LID_EDGES = {'b': E_LO, 'r': E_LO, 't': E_LO, 'l': E_LO}


def front_window(p: Params):
    """(centre x, centre y, width, height) of the display aperture, panel mm."""
    return (p.ow / 2, p.oh - p.disp_centre_z,
            p.disp_act_w + 2 * p.disp_window_margin,
            p.disp_act_h + 2 * p.disp_window_margin)


def build_front(p: Params) -> list[str]:
    """Display window, button hole, engraved title and birds."""
    out = [poly(panel_outline(p.ow, p.oh, p, FRONT_EDGES))]

    # Panel y runs downward in SVG, so convert heights from the box bottom.
    cx, cy, win_w, win_h = front_window(p)
    out.append(rrect(cx - win_w / 2, cy - win_h / 2, win_w, win_h,
                     p.disp_corner_r))

    # Pocket outline for the module PCB, engraved as a placement guide only.
    out.append(rrect(cx - p.disp_pcb_w / 2,
                     cy - win_h / 2 - p.disp_act_off_y,
                     p.disp_pcb_w, p.disp_pcb_h, 1.0, ENG))

    out.append(circle(cx, p.oh - p.btn_centre_z, p.btn_hole_d))
    out += build_front_decor(p)
    return out


def build_front_decor(p: Params) -> list[str]:
    """
    Engraved title and birds, laid out around the openings.

    Free area on this panel is only what the window, the button and the
    finger joints leave: a column each side of the display, a band between
    display and button, and the strip along the bottom. The title takes the
    bottom strip; a bird sits on a twig in each column, facing the screen,
    and the rest are distant marks that fill the corners without crowding.
    """
    out = []
    _, disp_cy, _, win_h = front_window(p)
    baseline = p.oh - p.title_baseline_z
    out += decor.script_text(p.title, p.ow / 2, baseline, p.title_xheight,
                             max_width=p.ow - 2 * (p.decor_inset + 3.0))

    # The engraved PCB outline, not the window, is what the decoration has
    # to stay clear of: it is 42 mm wide and the widest thing on the panel.
    pocket_l = p.ow / 2 - p.disp_pcb_w / 2
    pocket_r = p.ow / 2 + p.disp_pcb_w / 2
    pocket_b = disp_cy + win_h / 2 + (p.disp_pcb_h - win_h) / 2
    col_l, col_r = p.decor_inset, p.ow - p.decor_inset
    col_w = pocket_l - col_l - 1.5          # usable width of one column

    # A bird on a twig in each column, facing inward. Different sizes and
    # heights: a mirrored pair at matching heights reads as a logo, not as
    # two birds that happen to have landed on the box.
    ly = disp_cy + win_h / 2 - 1.0
    out += decor.branch(col_l, ly, col_w)
    out += decor.bird_perched(col_l + 1.0, ly, min(15.0, col_w))

    ry = disp_cy - win_h / 2 + 12.0
    out += decor.branch(pocket_r + 1.5, ry, col_w, flip=True)
    out += decor.bird_perched(pocket_r + 3.0, ry, min(12.5, col_w - 2.0),
                              flip=True)

    # Distant birds: two above the display, two flanking the button.
    top = p.decor_inset + 3.0
    out += decor.bird_swallow(col_l + 3.0, top + 6.0, 8.0)
    out += decor.bird_swallow(col_r - 12.0, top + 3.5, 6.0, flip=True)

    btn_y = p.oh - p.btn_centre_z
    band = (pocket_b + btn_y) / 2
    out += decor.bird_flying(col_l + 8.0, band + 4.0, 13.0)
    out += decor.bird_swallow(col_r - 20.0, band + 2.0, 8.0, flip=True)
    return out


def build_back(p: Params) -> list[str]:
    """
    Service panel: vents, power-lead entry, and a pull slot.

    Press-fit rather than glued. Its tabs are cut undersize by
    back_clearance so it can be removed by hand; the other five panels are
    glued. Without this the box would be sealed and the Pi unreachable.
    """
    loose = p.kerf - 2 * p.back_clearance
    out = [poly(panel_outline(p.ow, p.oh, p, FRONT_EDGES, kerf=loose))]

    # Pull slot, sized for two fingertips.
    pull_y = p.oh * 0.46
    out.append(rrect(p.ow / 2 - p.pull_slot_w / 2, pull_y,
                     p.pull_slot_w, p.pull_slot_h, p.pull_slot_h / 2))
    out.append(text(p.ow / 2, pull_y - 4.0, "TIRER", 4.0))

    # Exhaust high, intake low, both clear of the cable entry.
    out += vents(p.t + 6, p.t + 6, p.ow - 2 * (p.t + 6), p.oh * 0.34, p)

    cy = p.oh - p.cable_slot_z
    out.append(rrect(p.ow / 2 - p.cable_slot_w / 2, cy - p.cable_slot_h / 2,
                     p.cable_slot_w, p.cable_slot_h, p.cable_slot_h / 2))
    for dx in (-1, 1):
        out.append(circle(p.ow / 2 + dx * (p.cable_slot_w / 2 + 5.0),
                          cy, p.tie_hole_d))
    out.append(text(p.ow / 2, cy + 12.0, "5V  GND", 4.0))
    return out


def build_side(p: Params, mirror: bool) -> list[str]:
    """
    Left/right walls. Identical, so cut two of the same part.

    Two vent bands: low ones feed cool air across the Pi, high ones let it
    leave. Without the pair there is no convection, only a warm pocket.
    """
    out = [poly(panel_outline(p.od, p.oh, p, SIDE_EDGES))]
    inset = p.t + 6
    w = p.od - 2 * inset
    # Panel v runs downward, so "low in the box" is a large v.
    out += vents(inset, p.oh - inset - 26, w, 26, p)          # intake, bottom
    out += vents(inset, inset + 4, w, 30, p)                  # exhaust, top
    return out


def build_top(p: Params) -> list[str]:
    """Mic port with grille, plus exhaust vents."""
    out = [poly(panel_outline(p.ow, p.od, p, LID_EDGES))]

    # Mic sits to one side; vents to the other, so warm air does not wash
    # straight over the acoustic port.
    mx, my = p.ow * 0.27, p.od / 2
    out.append(circle(mx, my, p.mic_port_d))
    for ring in range(1, p.mic_grille_rings + 1):
        rad = 5.0 + 3.4 * ring
        n = 8 * ring
        for i in range(n):
            a = 2 * math.pi * i / n
            out.append(circle(mx + rad * math.cos(a), my + rad * math.sin(a),
                              p.mic_grille_d))
    out.append(rrect(mx - p.mic_pcb_w / 2 - 0.3, my - p.mic_pcb_h / 2 - 0.3,
                     p.mic_pcb_w + 0.6, p.mic_pcb_h + 0.6, 0.8, ENG))
    out += vents(p.ow * 0.52, p.t + 6, p.ow * 0.40, p.od - 2 * (p.t + 6), p)
    return out


def build_bottom(p: Params) -> list[str]:
    """Pi mounting holes and intake vents."""
    out = [poly(panel_outline(p.ow, p.od, p, LID_EDGES))]

    # Centre the Pi, then place holes from its board corner.
    ox = (p.ow - p.pi_w) / 2
    oy = (p.od - p.pi_d) / 2
    hx0 = ox + p.pi_hole_inset
    hy0 = oy + p.pi_hole_inset
    for dx in (0.0, p.pi_hole_dx):
        for dy in (0.0, p.pi_hole_dy):
            out.append(circle(hx0 + dx, hy0 + dy, p.pi_hole_d))
    out.append(rrect(ox, oy, p.pi_w, p.pi_d, 3.0, ENG))
    out.append(text(p.ow / 2, oy - 3.0, "Pi 3B", 4.0))

    # Deliberately no vents here. The board covers all but ~6 mm of this
    # panel, and a downward vent is blocked by whatever the box stands on.
    # Convection is handled by low slots in the side walls and exhaust in
    # the top panel instead.
    return out


def build_disp_frame(p: Params) -> list[str]:
    """
    Spacer that turns the front panel into a pocket for the module.

    Glue to the inside of the front panel, aligned with the engraved outline.
    Two of these give a 6 mm pocket, enough to clear a soldered header.
    """
    w = p.disp_pcb_w + 16.0
    h = p.disp_pcb_h + 16.0
    out = [rrect(0, 0, w, h, 2.0)]
    ow_ = p.disp_pcb_w + p.disp_pocket_slack
    oh_ = p.disp_pcb_h + p.disp_pocket_slack
    out.append(rrect((w - ow_) / 2, (h - oh_) / 2, ow_, oh_,
                     p.disp_corner_r))
    out.append(text(w / 2, h - 4.0, "ECRAN", 4.0))
    return out


def build_mic_frame(p: Params) -> list[str]:
    """Retainer holding the mic breakout against the top panel's port."""
    w = p.mic_pcb_w + 14.0
    h = p.mic_pcb_h + 14.0
    out = [rrect(0, 0, w, h, 2.0)]
    ow_ = p.mic_pcb_w + 0.4
    oh_ = p.mic_pcb_h + 0.4
    out.append(rrect((w - ow_) / 2, (h - oh_) / 2, ow_, oh_, 0.8))
    out.append(text(w / 2, h - 3.0, "MIC", 3.5))
    return out


def build_pi_pad(p: Params) -> list[str]:
    """
    Spacer pad under the Pi.

    Raising the board a few millimetres lets air move underneath it rather
    than sitting in a dead layer against the base. Cut four; stack as needed
    and pass the M2.5 screws through.
    """
    d = p.pi_hole_d + 7.0
    out = [circle(d / 2, d / 2, d)]
    out.append(circle(d / 2, d / 2, p.pi_hole_d))
    return out


# =====================================================================
#  sheet assembly
# =====================================================================
def bbox(body: list[str]) -> tuple[float, float]:
    """Crude extent from the numbers in the emitted markup."""
    import re
    xs, ys = [0.0], [0.0]
    for el in body:
        for m in re.finditer(r'points="([^"]+)"', el):
            for pair in m.group(1).split():
                x, y = pair.split(",")
                xs.append(float(x)); ys.append(float(y))
        for m in re.finditer(r'x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"', el):
            x, y, w, h = (float(g) for g in m.groups())
            xs += [x, x + w]; ys += [y, y + h]
        for m in re.finditer(r'cx="([-\d.]+)" cy="([-\d.]+)" r="([-\d.]+)"', el):
            cx, cy, r = (float(g) for g in m.groups())
            xs += [cx - r, cx + r]; ys += [cy - r, cy + r]
    return max(xs), max(ys)


def place(body: list[str], dx: float, dy: float, name: str) -> str:
    inner = "\n    ".join(body)
    return (f'  <g id="{name}" transform="translate({dx:.3f},{dy:.3f})">\n'
            f'    {inner}\n  </g>')


def build_sheet(p: Params) -> tuple[str, float, float]:
    parts = [
        ("front", build_front(p)),
        ("back", build_back(p)),
        ("side_left", build_side(p, False)),
        ("side_right", build_side(p, True)),
        ("top", build_top(p)),
        ("bottom", build_bottom(p)),
        ("disp_frame_1", build_disp_frame(p)),
        ("disp_frame_2", build_disp_frame(p)),
        ("mic_frame", build_mic_frame(p)),
        ("pi_pad_1", build_pi_pad(p)),
        ("pi_pad_2", build_pi_pad(p)),
        ("pi_pad_3", build_pi_pad(p)),
        ("pi_pad_4", build_pi_pad(p)),
    ]

    # Simple shelf packing: fill a row until it would exceed the sheet width,
    # then start a new row at the tallest part's height.
    sheet_w = 600.0
    x, y, row_h = p.margin, p.margin, 0.0
    placed, used_w = [], 0.0
    for name, body in parts:
        w, h = bbox(body)
        if x + w + p.margin > sheet_w and x > p.margin:
            x, y = p.margin, y + row_h + p.gap
            row_h = 0.0
        placed.append(place(body, x, y, name))
        x += w + p.gap
        row_h = max(row_h, h)
        used_w = max(used_w, x)
    total_h = y + row_h + p.margin

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{used_w:.2f}mm" height="{total_h:.2f}mm" '
        f'viewBox="0 0 {used_w:.2f} {total_h:.2f}">\n'
        f'  <!-- PiouPiou enclosure. RED = cut, BLUE = engrave. '
        f'Units mm. Material {p.t} mm MDF, kerf {p.kerf} mm. -->\n'
        + "\n".join(placed) + "\n</svg>\n"
    )
    return svg, used_w, total_h


# =====================================================================
#  self-check
# =====================================================================
def verify_joints(p: Params) -> list[str]:
    """
    Assert that every mating edge pair is genuinely complementary.

    segments() depends only on (length, target, ends_high), so a matching
    length plus opposite end phase guarantees interlock. This checks it
    explicitly rather than relying on that reasoning surviving future edits
    to the box dimensions.
    """
    pairs = [
        ("front.left  / side.front", p.oh, True, False),
        ("front.right / side.front", p.oh, True, False),
        ("front.top   / top.front ", p.ow, True, False),
        ("front.bot   / bottom.fr ", p.ow, True, False),
        ("side.top    / top.left  ", p.od, True, False),
        ("side.bot    / bottom.lft", p.od, True, False),
    ]
    report = []
    for name, length, a_hi, b_hi in pairs:
        sa = segments(length, p.finger, a_hi)
        sb = segments(length, p.finger, b_hi)
        ok = (len(sa) == len(sb)
              and all(x[2] != y[2] for x, y in zip(sa, sb))
              and all(abs(x[0] - y[0]) < 1e-9 for x, y in zip(sa, sb)))
        tabs = sum(1 for x in sa if x[2])
        report.append(f"  {name}  len={length:6.1f}  n={len(sa):2d}  "
                      f"tabs={tabs}  {'OK' if ok else 'MISMATCH'}")
        if not ok:
            raise AssertionError(f"joint pair not complementary: {name}")
    return report


def verify_rectilinear(svg: str) -> list[str]:
    """
    Assert every cut outline is strictly rectilinear.

    A finger joint is all right angles, so any segment that changes both x and
    y is a bug. An earlier version produced exactly that at corners where two
    edges had different phases: the path jumped straight from one profile to
    the other, cutting a diagonal spike across the corner. It was invisible on
    the front panel (whose edges are "high" at every corner) and only appeared
    on the sides and lids, so it survived a visual check of one panel.
    """
    import re
    report, bad = [], 0
    for g in re.finditer(r'<g id="([^"]+)"[^>]*>(.*?)</g>', svg, re.S):
        name, body = g.group(1), g.group(2)
        for poly in re.finditer(r'<polygon points="([^"]+)"', body):
            pts = [tuple(float(v) for v in pr.split(','))
                   for pr in poly.group(1).split()]
            n = len(pts)
            diag = sum(1 for i in range(n)
                       if abs(pts[i][0] - pts[(i + 1) % n][0]) > 1e-9
                       and abs(pts[i][1] - pts[(i + 1) % n][1]) > 1e-9)
            if diag:
                bad += diag
                report.append(f"  {name}: {diag} diagonal segment(s)")
    if bad:
        report.append(f"  TOTAL {bad} - outlines are not rectilinear")
        raise AssertionError(f"{bad} diagonal cut segments found")
    report.append("  every cut outline is rectilinear")
    return report


def verify_decor(p: Params) -> list[str]:
    """
    Assert the engraved decoration keeps clear of everything that matters.

    The title and the birds are placed from panel dimensions, so changing
    the box height or the display position silently moves them. Flattening
    the paths and measuring is cheaper than discovering on the cut part that
    a bird's tail crosses the window or that the descender of "piafs" runs
    into a finger joint.
    """
    cx, cy, win_w, win_h = front_window(p)
    pts = decor.flatten(build_front_decor(p))
    border = p.t + 0.8
    btn_r = p.btn_hole_d / 2

    zones = {
        "panel border": min(min(x, y, p.ow - x, p.oh - y)
                            for x, y in pts) - border,
        "window": min(max(abs(x - cx) - win_w / 2, abs(y - cy) - win_h / 2)
                      for x, y in pts),
        "pcb pocket": min(max(abs(x - cx) - p.disp_pcb_w / 2,
                              abs(y - (cy - win_h / 2 - p.disp_act_off_y
                                       + p.disp_pcb_h / 2)) - p.disp_pcb_h / 2)
                          for x, y in pts),
        "button": min(math.hypot(x - cx, y - (p.oh - p.btn_centre_z))
                      for x, y in pts) - btn_r,
    }
    report = [f"  {len(pts)} sampled points on the engraving"]
    for name, clear in zones.items():
        report.append(f"  clearance to {name:<13} {clear:6.2f} mm"
                      f"{'' if clear > 0.5 else '   <-- TOO CLOSE'}")
    tight = [n for n, c in zones.items() if c <= 0.5]
    if tight:
        raise AssertionError("decoration fouls " + ", ".join(tight))
    w, up, down = decor.script_extent(
        p.title, p.title_xheight, max_width=p.ow - 2 * (p.decor_inset + 3.0))
    report.append(f"  title \"{p.title}\"  {w:.1f} mm wide, "
                  f"{up:.1f} up / {down:.1f} down from its baseline")
    return report


def check_fit(p: Params) -> list[str]:
    """Sanity-check that the contents actually fit, and flag tight spots."""
    out = []
    iw, idp, ih = p.ow - 2 * p.t, p.od - 2 * p.t, p.oh - 2 * p.t
    out.append(f"  inner volume        {iw:.0f} x {idp:.0f} x {ih:.0f} mm")
    out.append(f"  Pi clearance        x {(iw - p.pi_w) / 2:.1f} mm/side, "
               f"y {(idp - p.pi_d) / 2:.1f} mm/side")
    if (idp - p.pi_d) / 2 < 3.0:
        out.append("  WARNING: under 3 mm/side - USB and Ethernet shells "
                   "overhang the PCB edge by ~2 mm")
    disp_top_z = p.disp_centre_z + p.disp_act_h / 2 + p.disp_act_off_y
    disp_bot_z = disp_top_z - p.disp_pcb_h
    out.append(f"  display module z    {disp_bot_z:.1f} .. {disp_top_z:.1f} mm "
               f"(inner {p.t:.0f} .. {p.oh - p.t:.0f})")
    if disp_top_z > p.oh - p.t or disp_bot_z < p.t:
        out.append("  WARNING: display module does not fit the front panel")
    if disp_bot_z < 20.0:
        out.append("  NOTE: module reaches low enough to meet the Pi's "
                   "GPIO header; check wiring clearance")
    win_w = p.disp_act_w + 2 * p.disp_window_margin
    out.append(f"  window              {win_w:.1f} x "
               f"{p.disp_act_h + 2 * p.disp_window_margin:.1f} mm, "
               f"corner r {p.disp_corner_r:.1f} mm")
    if p.disp_corner_r > win_w / 2:
        out.append("  WARNING: corner radius exceeds half the window width")
    out.append(f"  button z            {p.btn_centre_z:.1f} mm "
               f"(module starts at {disp_bot_z:.1f})")
    if p.btn_centre_z + p.btn_hole_d / 2 > disp_bot_z:
        out.append("  WARNING: button overlaps the display module")
    return out


def main():
    p = Params()
    print("joint check:")
    for line in verify_joints(p):
        print(line)
    print("decor check:")
    for line in verify_decor(p):
        print(line)
    print("fit check:")
    for line in check_fit(p):
        print(line)
    print()

    svg, w, h = build_sheet(p)
    print("geometry check:")
    for line in verify_rectilinear(svg):
        print(line)
    print()
    out = "/home/romain/piou/box/piou_box.svg"
    with open(out, "w") as f:
        f.write(svg)
    print(f"wrote {out}")
    print(f"sheet used: {w:.1f} x {h:.1f} mm")
    print(f"outer box:  {p.ow} x {p.od} x {p.oh} mm")
    inner = (p.ow - 2 * p.t, p.od - 2 * p.t, p.oh - 2 * p.t)
    print(f"inner:      {inner[0]:.0f} x {inner[1]:.0f} x {inner[2]:.0f} mm"
          f"   (Pi is {p.pi_w} x {p.pi_d})")


if __name__ == "__main__":
    main()
