#!/usr/bin/env python3
"""
Throwaway visual check: rasterise one part of the generated SVG to a PNG.

The sheet is meant to be read by a laser, not by a person, so nothing in the
build pipeline ever shows what a panel actually looks like. This renders the
subset of SVG the generator emits (polygon, rect, circle, path with M/L/C/Z)
so the decoration can be judged by eye before it is cut.

Not imported by piou_box.py; no third-party dependency, hence the hand-rolled
PNG writer.
"""

from __future__ import annotations

import re
import struct
import sys
import zlib


# ---------------------------------------------------------------- png
def write_png(path, pixels, w, h):
    """pixels: bytearray of w*h grayscale bytes."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += pixels[y * w:(y + 1) * w]

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


# ---------------------------------------------------------------- geometry
def bez(p0, p1, p2, p3, n=24):
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u*u*u*p0[0] + 3*u*u*t*p1[0] + 3*u*t*t*p2[0] + t*t*t*p3[0],
                    u*u*u*p0[1] + 3*u*u*t*p1[1] + 3*u*t*t*p2[1] + t*t*t*p3[1]))
    return out


NUM = re.compile(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?')


def parse_path(d):
    """Only the commands the generator emits: M, L, C, Z (absolute)."""
    toks = re.findall(r'[MLCZmlczHhVv]|[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', d)
    polys, cur, start, i, pos = [], [], None, 0, (0.0, 0.0)
    cmd = None
    while i < len(toks):
        tk = toks[i]
        if tk.isalpha():
            cmd = tk
            i += 1
            if cmd in "Zz":
                if cur:
                    cur.append(start)
                    polys.append(cur)
                    cur = []
                continue
        nums = []
        while i < len(toks) and not toks[i].isalpha():
            nums.append(float(toks[i]))
            i += 1
        if cmd == "M":
            for j in range(0, len(nums), 2):
                pos = (nums[j], nums[j + 1])
                if j == 0:
                    if cur:
                        polys.append(cur)
                    cur = [pos]
                    start = pos
                else:
                    cur.append(pos)
        elif cmd == "L":
            for j in range(0, len(nums), 2):
                pos = (nums[j], nums[j + 1])
                cur.append(pos)
        elif cmd == "C":
            for j in range(0, len(nums), 6):
                p1 = (nums[j], nums[j + 1])
                p2 = (nums[j + 2], nums[j + 3])
                p3 = (nums[j + 4], nums[j + 5])
                cur += bez(pos, p1, p2, p3)
                pos = p3
    if cur:
        polys.append(cur)
    return polys


def arc_pts(cx, cy, rx, ry, a0, a1, n=10):
    import math
    return [(cx + rx * math.cos(a0 + (a1 - a0) * i / n),
             cy + ry * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def rrect_pts(x, y, w, h, rx, ry):
    import math
    if rx <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    p = []
    p += arc_pts(x + w - rx, y + ry, rx, ry, -math.pi / 2, 0)
    p += arc_pts(x + w - rx, y + h - ry, rx, ry, 0, math.pi / 2)
    p += arc_pts(x + rx, y + h - ry, rx, ry, math.pi / 2, math.pi)
    p += arc_pts(x + rx, y + ry, rx, ry, math.pi, 1.5 * math.pi)
    p.append(p[0])
    return p


def elements(body):
    """(polyline, colour) for every drawable element in a group body."""
    out = []
    for m in re.finditer(r'<(polygon|rect|circle|path)\b([^>]*)/>', body):
        tag, attrs = m.group(1), m.group(2)
        eng = "#0000ff" in attrs
        if tag == "polygon":
            pts = [tuple(float(v) for v in pr.split(','))
                   for pr in re.search(r'points="([^"]+)"', attrs).group(1).split()]
            out.append((pts + [pts[0]], eng))
        elif tag == "rect":
            g = lambda k, d=0.0: float(re.search(rf'{k}="([-\d.]+)"', attrs).group(1)) \
                if re.search(rf'{k}="([-\d.]+)"', attrs) else d
            out.append((rrect_pts(g("x"), g("y"), g("width"), g("height"),
                                  g("rx"), g("ry")), eng))
        elif tag == "circle":
            g = lambda k: float(re.search(rf'{k}="([-\d.]+)"', attrs).group(1))
            r = g("r")
            out.append((arc_pts(g("cx"), g("cy"), r, r, 0, 6.2832, 32), eng))
        else:
            d = re.search(r'\sd="([^"]+)"', attrs).group(1)
            for pl in parse_path(d):
                out.append((pl, eng))
    return out


# ---------------------------------------------------------------- raster
def render(body, out_png, px_per_mm=6, pad=4, ss=3):
    polys = elements(body)
    xs = [p[0] for pl, _ in polys for p in pl]
    ys = [p[1] for pl, _ in polys for p in pl]
    x0, y0 = min(xs) - pad, min(ys) - pad
    w = int((max(xs) + pad - x0) * px_per_mm)
    h = int((max(ys) + pad - y0) * px_per_mm)
    W, H = w * ss, h * ss
    buf = bytearray(b"\xff" * (W * H))

    def dot(px, py, val):
        if 0 <= px < W and 0 <= py < H:
            i = py * W + px
            if buf[i] > val:
                buf[i] = val

    def line(a, b, val, rad):
        ax = (a[0] - x0) * px_per_mm * ss
        ay = (a[1] - y0) * px_per_mm * ss
        bx = (b[0] - x0) * px_per_mm * ss
        by = (b[1] - y0) * px_per_mm * ss
        n = max(2, int(max(abs(bx - ax), abs(by - ay))) + 1)
        for i in range(n + 1):
            t = i / n
            px, py = ax + (bx - ax) * t, ay + (by - ay) * t
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if dx * dx + dy * dy <= rad * rad:
                        dot(int(px) + dx, int(py) + dy, val)

    for pl, eng in polys:
        val, rad = (70, 1) if eng else (190, 1)
        for a, b in zip(pl, pl[1:]):
            line(a, b, val, rad)

    small = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            s = 0
            for dy in range(ss):
                row = (y * ss + dy) * W + x * ss
                for dx in range(ss):
                    s += buf[row + dx]
            small[y * w + x] = s // (ss * ss)
    write_png(out_png, small, w, h)
    return w, h


def main():
    svg_path = sys.argv[1] if len(sys.argv) > 1 else "/home/romain/piou/box/piou_box.svg"
    part = sys.argv[2] if len(sys.argv) > 2 else "front"
    out = sys.argv[3] if len(sys.argv) > 3 else "/tmp/part.png"
    svg = open(svg_path).read()
    m = re.search(rf'<g id="{part}"[^>]*>(.*?)\n  </g>', svg, re.S)
    if not m:
        print(f"no part {part!r}")
        sys.exit(1)
    w, h = render(m.group(1), out, px_per_mm=int(sys.argv[4]) if len(sys.argv) > 4 else 6)
    print(f"{out}  {w}x{h}px")


if __name__ == "__main__":
    main()
