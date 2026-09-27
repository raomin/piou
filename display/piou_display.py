#!/usr/bin/env python3
"""
piou_display -- show BirdNET-Go detections on a 1.69" ST7789V3 TFT (240x280).

Layout is photo-first: the species photo fills the panel, and the French
common name, time and confidence sit on top of it behind a bottom scrim.

Detections are read from the local BirdNET-Go API rather than from its
push-notification hook, because the built-in detection notification only
fires for *new* species while the panel should react to every detection.

Species photos come from BirdNET-Go's own image proxy, which already
resolves and caches upstream images. Every photo we render is additionally
stored here as a ready-to-blit 240x280 JPEG, so a species seen once is
displayed instantly and with no network afterwards.
"""

from __future__ import annotations

import argparse
import io
import logging
import os
import queue
import re
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from piou_button import LONG_PRESS, SHORT_PRESS, Button
from piou_listen import LevelMonitor
from piou_sse import (PENDING_ACTIVE, PENDING_REJECTED,
                      DetectionStream)

LOG = logging.getLogger("piou")

WIDTH, HEIGHT = 240, 280

# --- palette -------------------------------------------------------------
FG            = (255, 255, 255)
FG_MUTED      = (228, 230, 236)
FG_DIM        = (198, 201, 210)
CONF_HIGH     = (94, 214, 122)
CONF_MED      = (240, 200, 90)
CONF_LOW      = (240, 150, 90)
BADGE_BG      = (228, 92, 84)
SKY_TOP       = (14, 18, 26)
SKY_BOTTOM    = (30, 38, 52)

JOURS = ("lun", "mar", "mer", "jeu", "ven", "sam", "dim")
MOIS = ("janv", "févr", "mars", "avr", "mai", "juin",
        "juil", "août", "sept", "oct", "nov", "déc")


def date_fr(dt):
    return f"{JOURS[dt.weekday()]} {dt.day:02d} {MOIS[dt.month - 1]}"


POWER_MENU_TIMEOUT = 12.0   # seconds before the power menu self-cancels

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/truetype/liberation",
    "/usr/share/fonts/TTF",
]


# =========================================================================
#  fonts
# =========================================================================
def _find_font(*names: str) -> str | None:
    for d in FONT_DIRS:
        for n in names:
            p = Path(d) / n
            if p.exists():
                return str(p)
    return None


class Fonts:
    """Lazily-built, size-memoised font cache."""

    def __init__(self) -> None:
        self._bold = _find_font("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf")
        self._reg = _find_font("DejaVuSans.ttf", "LiberationSans-Regular.ttf")
        # Oblique lives in fonts-dejavu-extra and is often absent on Lite;
        # fall back to the regular face rather than failing to draw.
        self._ital = _find_font(
            "DejaVuSans-Oblique.ttf", "LiberationSans-Italic.ttf"
        ) or self._reg
        if not (self._bold and self._reg):
            LOG.warning("no TrueType fonts found, falling back to bitmap font")
        self._cache: dict[tuple[str, int], ImageFont.ImageFont] = {}

    def _get(self, path: str | None, size: int):
        if path is None:
            return ImageFont.load_default()
        key = (path, size)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(path, size)
        return self._cache[key]

    def bold(self, size: int):
        return self._get(self._bold, size)

    def regular(self, size: int):
        return self._get(self._reg, size)

    def italic(self, size: int):
        return self._get(self._ital, size)


# =========================================================================
#  model
# =========================================================================
@dataclass
class Detection:
    id: int
    common_name: str
    scientific_name: str
    confidence: float
    clock: str          # "HH:MM"
    is_new: bool

    @classmethod
    def from_api(cls, d: dict) -> "Detection":
        return cls(
            id=int(d.get("id") or 0),
            common_name=(d.get("commonName") or "?").strip(),
            scientific_name=(d.get("scientificName") or "").strip(),
            confidence=float(d.get("confidence") or 0.0),
            clock=(d.get("time") or "")[:5],
            is_new=bool(
                d.get("isNewSpecies")
                or d.get("isNewThisYear")
                or d.get("isNewThisSeason")
            ),
        )


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "unknown"


def conf_color(c: float):
    if c >= 0.85:
        return CONF_HIGH
    if c >= 0.70:
        return CONF_MED
    return CONF_LOW


# =========================================================================
#  species photos
# =========================================================================
class PhotoStore:
    """
    Disk cache of 240x280 cover-cropped species photos.

    Cache hits are pure local reads, which is what makes the panel work with
    no internet once a species has been seen.
    """

    def __init__(self, cache_dir: Path, api_base: str, timeout: float = 8.0):
        self.dir = cache_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        # Species with no upstream photo: don't retry them every detection.
        self._missing: set[str] = set()

    def path_for(self, scientific_name: str) -> Path:
        return self.dir / f"{slugify(scientific_name)}.jpg"

    def get_cached(self, scientific_name: str) -> Image.Image | None:
        p = self.path_for(scientific_name)
        if not p.exists():
            return None
        try:
            with Image.open(p) as im:
                return im.convert("RGB").copy()
        except Exception as e:  # corrupt/truncated file: drop it and refetch
            LOG.warning("bad cached photo %s: %s", p.name, e)
            p.unlink(missing_ok=True)
            return None

    def fetch(self, scientific_name: str, attempts: int = 4) -> Image.Image | None:
        """
        Download, cover-crop and store a species photo.

        BirdNET-Go's proxy answers 503 + Retry-After while it resolves the
        image on a background goroutine, so a cold species needs a couple of
        polite retries before the bytes exist.
        """
        if not scientific_name or scientific_name in self._missing:
            return None

        url = f"{self.api_base}/api/v2/media/image/{requests.utils.quote(scientific_name)}"
        for attempt in range(attempts):
            try:
                r = requests.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                LOG.debug("photo fetch error for %s: %s", scientific_name, e)
                return None

            if r.status_code == 200 and r.content:
                try:
                    with Image.open(io.BytesIO(r.content)) as im:
                        cover = fit_source(im.convert("RGB"))
                except Exception as e:
                    LOG.warning("undecodable photo for %s: %s", scientific_name, e)
                    return None
                tmp = self.path_for(scientific_name).with_suffix(".tmp")
                cover.save(tmp, "JPEG", quality=88, optimize=True)
                tmp.replace(self.path_for(scientific_name))
                LOG.info("cached photo for %s", scientific_name)
                return cover

            if r.status_code == 404:
                LOG.info("no upstream photo for %s", scientific_name)
                self._missing.add(scientific_name)
                return None

            if r.status_code == 503:  # still resolving
                delay = float(r.headers.get("Retry-After") or 3)
                if attempt < attempts - 1:
                    time.sleep(min(delay, 5.0))
                continue

            LOG.debug("photo HTTP %s for %s", r.status_code, scientific_name)
            return None
        return None


SOURCE_MAX = 480          # cached source photos are bounded, not pre-cropped
PHOTO_BAND_H = 170        # rows reserved for the photo above the text block


def fit_source(im: Image.Image, limit: int = SOURCE_MAX) -> Image.Image:
    """Shrink an incoming photo to a sane cache size, preserving aspect."""
    if max(im.width, im.height) <= limit:
        return im
    scale = limit / max(im.width, im.height)
    return im.resize((max(1, int(im.width * scale)),
                      max(1, int(im.height * scale))), Image.LANCZOS)


def contain(im: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to fit *inside* w x h, preserving aspect. Nothing is cropped."""
    scale = min(w / im.width, h / im.height)
    return im.resize((max(1, int(round(im.width * scale))),
                      max(1, int(round(im.height * scale)))), Image.LANCZOS)


def photo_backdrop(im: Image.Image) -> Image.Image:
    """
    A blurred, darkened enlargement of the photo, filling the whole panel.

    Bird photos are overwhelmingly landscape while the panel is portrait, so a
    cover-crop would discard most of the width and routinely cut the bird.
    Letterboxing the full photo over this backdrop keeps the subject intact and
    makes the leftover space look intentional.
    """
    bg = cover_crop(im, WIDTH, HEIGHT).filter(ImageFilter.GaussianBlur(14))
    return ImageEnhance.Brightness(bg).enhance(0.45)


def cover_crop(im: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to fill w x h, centre-cropping the overflow."""
    scale = max(w / im.width, h / im.height)
    new = (max(w, int(round(im.width * scale))), max(h, int(round(im.height * scale))))
    im = im.resize(new, Image.LANCZOS)
    left = (im.width - w) // 2
    top = (im.height - h) // 2
    return im.crop((left, top, left + w, top + h))


# =========================================================================
#  rendering
# =========================================================================
def _scrim(height: int, top_alpha: int, bottom_alpha: int,
           gamma: float = 0.62) -> Image.Image:
    """
    A 1px-wide vertical alpha ramp, stretched by the caller.

    gamma < 1 front-loads the darkening, so the rows carrying the small
    secondary text are already near-opaque instead of still half clear.
    A plain linear ramp leaves grey-on-white text unreadable over a bright
    photo, which is the common case for a bird against sky or snow.
    """
    ramp = Image.new("L", (1, height))
    px = ramp.load()
    for y in range(height):
        t = (y / max(height - 1, 1)) ** gamma
        px[0, y] = int(round(top_alpha + (bottom_alpha - top_alpha) * t))
    return ramp


def _text_shadowed(draw, xy, text, font, fill, shadow=(0, 0, 0), offset=1):
    """Small text needs its own shadow; the scrim alone cannot guarantee it."""
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _fit_lines(draw, text: str, font_for, max_w: int, max_lines: int,
               start: int, floor: int):
    """
    Shrink the font until `text` wraps into at most `max_lines` lines that
    each fit `max_w`. Returns (font, lines).
    """
    words = text.split()
    for size in range(start, floor - 1, -1):
        f = font_for(size)
        lines, cur = [], ""
        for wd in words:
            trial = f"{cur} {wd}".strip()
            if draw.textlength(trial, font=f) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = wd
        if cur:
            lines.append(cur)
        if len(lines) <= max_lines and all(
            draw.textlength(l, font=f) <= max_w for l in lines
        ):
            return f, lines
    f = font_for(floor)
    return f, [text]


def render_detection(det: Detection, photo: Image.Image | None,
                     fonts: Fonts, provisional: bool = False) -> Image.Image:
    """
    `provisional` renders a pending detection: the species is known but
    BirdNET-Go has not finished accumulating confirmations, so no confidence
    figure is shown. Claiming a percentage that can still change (or be
    rejected outright) would be worse than saying nothing.
    """
    if photo is not None:
        frame = photo_backdrop(photo)
        # Whole photo, uncropped, centred in the band above the text block.
        fg = contain(photo, WIDTH, PHOTO_BAND_H)
        frame.paste(fg, ((WIDTH - fg.width) // 2, (PHOTO_BAND_H - fg.height) // 2))
    else:
        frame = gradient_bg()

    draw = ImageDraw.Draw(frame)

    # Bottom scrim so text stays legible over any photo.
    band_h = HEIGHT - PHOTO_BAND_H + 20
    band = Image.new("RGB", (WIDTH, band_h), (0, 0, 0))
    band.putalpha(_scrim(band_h, 0, 248).resize((WIDTH, band_h)))
    frame.paste(band, (0, HEIGHT - band_h), band)

    # --- confidence bar pinned to the very bottom ---
    bar_h = 4
    bar_y = HEIGHT - bar_h
    draw.rectangle([0, bar_y, WIDTH, HEIGHT], fill=(255, 255, 255, 40))
    if provisional:
        # Deliberately not a value: a short centred segment reads as activity
        # rather than as a confidence reading.
        draw.rectangle([WIDTH * 0.36, bar_y, WIDTH * 0.64, HEIGHT], fill=BRAND)
    else:
        fill_w = int(round(WIDTH * max(0.0, min(1.0, det.confidence))))
        draw.rectangle([0, bar_y, fill_w, HEIGHT], fill=conf_color(det.confidence))

    # --- meta row: time left, confidence right ---
    f_meta = fonts.regular(15)
    meta_y = bar_y - 6 - 15
    _text_shadowed(draw, (10, meta_y), det.clock, f_meta, FG_MUTED)
    if provisional:
        tag = "reconnaissance…"
        f_prov = fonts.regular(13)
        _text_shadowed(draw,
                       (WIDTH - 10 - draw.textlength(tag, font=f_prov), meta_y + 1),
                       tag, f_prov, BRAND)
    else:
        pct = f"{det.confidence * 100:.0f} %"
        _text_shadowed(draw, (WIDTH - 10 - draw.textlength(pct, font=f_meta), meta_y),
                       pct, f_meta, conf_color(det.confidence))

    # --- scientific name ---
    f_sci = fonts.italic(13)
    sci_y = meta_y - 4 - 14
    sci = det.scientific_name
    while sci and draw.textlength(sci, font=f_sci) > WIDTH - 20:
        sci = sci[:-2]
    _text_shadowed(draw, (10, sci_y), sci, f_sci, FG_DIM)

    # --- common name, growing upward from the scientific name ---
    f_name, lines = _fit_lines(
        draw, det.common_name, fonts.bold, WIDTH - 20, 2, 30, 15
    )
    line_h = f_name.size + 3
    name_y = sci_y - 5 - line_h * len(lines)
    for i, line in enumerate(lines):
        _text_shadowed(draw, (10, name_y + i * line_h), line, f_name, FG,
                       offset=2)

    # --- "new species" badge ---
    if det.is_new and not provisional:
        f_b = fonts.bold(11)
        label = "NOUVELLE ESPÈCE"
        tw = draw.textlength(label, font=f_b)
        bw, bh = tw + 14, 20
        bx, by = WIDTH - bw - 8, 8
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=10, fill=BADGE_BG)
        draw.text((bx + 7, by + 4), label, font=f_b, fill=FG)

    return frame


def gradient_bg() -> Image.Image:
    bg = Image.new("RGB", (WIDTH, HEIGHT))
    d = ImageDraw.Draw(bg)
    for y in range(HEIGHT):
        t = y / (HEIGHT - 1)
        d.line(
            [(0, y), (WIDTH, y)],
            fill=tuple(
                int(round(SKY_TOP[i] + (SKY_BOTTOM[i] - SKY_TOP[i]) * t))
                for i in range(3)
            ),
        )
    return bg



BRAND = (126, 200, 140)

# Live level meter, top-right of the header. Small on purpose: the box is on
# public display, so ambient conversation must not take over the screen.
METER_BARS = 5
METER_BAR_W = 7
METER_GAP = 2
METER_H = 13
METER_W = METER_BARS * METER_BAR_W + (METER_BARS - 1) * METER_GAP
METER_X = WIDTH - 10 - METER_W
METER_Y = 11
METER_FULL_DB = 24.0     # dB over the noise floor that lights every bar


def gradient_slice(y0: int, h: int, w: int = WIDTH) -> Image.Image:
    """
    The exact rows the standby gradient would paint at y0..y0+h.

    Partial updates must repaint their own background, so this reproduces the
    ramp rather than guessing a flat colour, keeping the tile seamless.
    """
    tile = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(tile)
    for i in range(h):
        t = (y0 + i) / (HEIGHT - 1)
        d.line([(0, i), (w, i)],
               fill=tuple(int(round(SKY_TOP[k] + (SKY_BOTTOM[k] - SKY_TOP[k]) * t))
                          for k in range(3)))
    return tile


def draw_meter(draw, x: int, y: int, over_db: float, hot: bool):
    """Five bars showing how far the level sits above the rolling background."""
    lit = 0 if over_db <= 0 else min(
        METER_BARS, int(over_db / METER_FULL_DB * METER_BARS) + 1)
    for i in range(METER_BARS):
        bx = x + i * (METER_BAR_W + METER_GAP)
        # Taller bars to the right reads as a level scale at a glance.
        bh = 5 + int(round(i * (METER_H - 5) / (METER_BARS - 1)))
        by = y + METER_H - bh
        if i < lit:
            col = BRAND if hot else (96, 112, 132)
        else:
            col = (44, 54, 70)
        draw.rectangle([bx, by, bx + METER_BAR_W - 1, y + METER_H - 1], fill=col)


def render_meter_tile(over_db: float, hot: bool) -> Image.Image:
    """Just the meter, on its own background, for a partial write."""
    tile = gradient_slice(METER_Y, METER_H, METER_W)
    draw_meter(ImageDraw.Draw(tile), 0, 0, over_db, hot)
    return tile


def _title(draw, fonts, text, sub=None, over_db=None, hot=False):
    """
    Common header: the node name, plus the live level meter on the right.

    `sub` is right-aligned to the left of the meter so the two never collide.
    """
    f = fonts.bold(15)
    draw.text((10, 10), text, font=f, fill=BRAND)
    if over_db is not None:
        draw_meter(draw, METER_X, METER_Y, over_db, hot)
    if sub:
        fs = fonts.regular(11)
        right = (METER_X - 6) if over_db is not None else (WIDTH - 10)
        draw.text((right - draw.textlength(sub, font=fs), 13),
                  sub, font=fs, fill=FG_DIM)
    draw.line([(10, 32), (WIDTH - 10, 32)], fill=(60, 70, 86))


def render_species_today(fonts, rows, count_today, over_db=None, hot=False):
    """Species seen today, most frequent first."""
    frame = gradient_bg()
    draw = ImageDraw.Draw(frame)
    _title(draw, fonts, "PiouPiou", f"{count_today} détections",
           over_db=over_db, hot=hot)

    if not rows:
        f = fonts.regular(13)
        msg = "aucune détection aujourd'hui"
        draw.text(((WIDTH - draw.textlength(msg, font=f)) / 2, 130),
                  msg, font=f, fill=FG_DIM)
        return frame

    f_name = fonts.bold(14)
    f_n = fonts.regular(13)
    y = 44
    for name, n, conf in rows[:9]:
        nlab = str(n)
        nw = draw.textlength(nlab, font=f_n)
        label = name
        if draw.textlength(label, font=f_name) > WIDTH - 30 - nw:
            while (draw.textlength(label + "…", font=f_name) > WIDTH - 30 - nw
                   and len(label) > 4):
                label = label[:-1]
            label += "…"
        draw.text((10, y), label, font=f_name, fill=FG)
        draw.text((WIDTH - 10 - nw, y + 1), nlab, font=f_n, fill=conf_color(conf))
        y += 25
        if y > HEIGHT - 24:
            break
    return frame


def render_sysinfo(fonts, info, over_db=None, hot=False):
    frame = gradient_bg()
    draw = ImageDraw.Draw(frame)
    _title(draw, fonts, "PiouPiou", "système", over_db=over_db, hot=hot)

    f_k = fonts.regular(12)
    f_v = fonts.bold(13)
    y = 46
    for k, v, col in info:
        draw.text((10, y), k, font=f_k, fill=FG_DIM)
        vw = draw.textlength(v, font=f_v)
        draw.text((WIDTH - 10 - vw, y - 1), v, font=f_v, fill=col)
        y += 24
    return frame


def render_power_menu(fonts, armed_s):
    frame = Image.new("RGB", (WIDTH, HEIGHT), (46, 14, 14))
    draw = ImageDraw.Draw(frame)
    _title(draw, fonts, "PiouPiou", "alimentation")

    f = fonts.bold(21)
    draw.text((10, 70), "Éteindre ?", font=f, fill=(255, 210, 210))

    f2 = fonts.regular(13)
    for i, line in enumerate((
        "appui court = confirmer",
        "appui long  = annuler",
    )):
        draw.text((10, 118 + i * 22), line, font=f2, fill=FG_MUTED)

    f3 = fonts.regular(12)
    msg = f"annulation auto dans {armed_s:.0f} s"
    draw.text((10, 178), msg, font=f3, fill=FG_DIM)

    # countdown bar
    frac = max(0.0, min(1.0, armed_s / POWER_MENU_TIMEOUT))
    draw.rectangle([0, HEIGHT - 6, WIDTH, HEIGHT], fill=(90, 40, 40))
    draw.rectangle([0, HEIGHT - 6, int(WIDTH * frac), HEIGHT], fill=(230, 90, 90))
    return frame


def render_shutting_down(fonts):
    frame = Image.new("RGB", (WIDTH, HEIGHT), (12, 12, 16))
    draw = ImageDraw.Draw(frame)
    f = fonts.bold(19)
    msg = "Arrêt en cours…"
    draw.text(((WIDTH - draw.textlength(msg, font=f)) / 2, 120),
              msg, font=f, fill=FG)
    f2 = fonts.regular(12)
    m2 = "attendre l'extinction de la LED"
    draw.text(((WIDTH - draw.textlength(m2, font=f2)) / 2, 152),
              m2, font=f2, fill=FG_DIM)
    return frame


def render_listening(fonts, level_db, floor_db, phase: int):
    """
    Shown the instant the mic hears something, while BirdNET-Go is still
    holding the detection in its pending window.

    The level meter is referenced to the rolling noise floor rather than to
    dBFS, so the bar reflects "how much louder than the background" -- which
    is what actually matters for whether the recogniser has a chance.
    """
    frame = gradient_bg()
    draw = ImageDraw.Draw(frame)
    _title(draw, fonts, "PiouPiou", "écoute")

    f1 = fonts.bold(19)
    draw.text((10, 52), "J'ai entendu", font=f1, fill=FG)
    draw.text((10, 76), "quelque chose\u2009!", font=f1, fill=FG)

    f2 = fonts.regular(14)
    dots = "." * (1 + phase % 3)
    draw.text((10, 116), f"Reconnaissance en cours{dots}", font=f2, fill=BRAND)

    # level bar, 0 = noise floor, full = +30 dB over it
    over = max(0.0, level_db - floor_db)
    frac = max(0.02, min(1.0, over / 30.0))
    bx, by, bw, bh = 10, 156, WIDTH - 20, 16
    draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8,
                           fill=(30, 38, 52))
    col = CONF_HIGH if over > 18 else (CONF_MED if over > 9 else CONF_LOW)
    draw.rounded_rectangle([bx, by, bx + int(bw * frac), by + bh], radius=8,
                           fill=col)
    f3 = fonts.regular(12)
    draw.text((10, 180), f"+{over:.0f} dB au-dessus du fond",
              font=f3, fill=FG_DIM)

    # a moving marker so the screen is visibly alive even at steady level
    f4 = fonts.regular(11)
    draw.text((10, 208), f"niveau {level_db:.0f} dBFS  ·  fond {floor_db:.0f} dBFS",
              font=f4, fill=FG_DIM)

    spinner = ["\u25e2", "\u25e3", "\u25e4", "\u25e5"][phase % 4]
    f5 = fonts.bold(20)
    draw.text((WIDTH - 34, 200), spinner, font=f5, fill=BRAND)
    return frame


def render_standby(fonts: Fonts, last: Detection | None,
                   count_today: int, online: bool,
                   over_db=None, hot=False) -> Image.Image:
    frame = gradient_bg()
    draw = ImageDraw.Draw(frame)
    now = datetime.now()

    _title(draw, fonts, "PiouPiou", over_db=over_db, hot=hot)

    f_clock = fonts.bold(58)
    clock = now.strftime("%H:%M")
    draw.text(((WIDTH - draw.textlength(clock, font=f_clock)) / 2, 62),
              clock, font=f_clock, fill=FG)

    f_date = fonts.regular(14)
    date = date_fr(now)
    draw.text(((WIDTH - draw.textlength(date, font=f_date)) / 2, 128),
              date, font=f_date, fill=FG_DIM)

    f_st = fonts.regular(13)
    status = "à l'écoute…" if online else "BirdNET-Go hors ligne"
    col = FG_MUTED if online else CONF_LOW
    draw.text(((WIDTH - draw.textlength(status, font=f_st)) / 2, 160),
              status, font=f_st, fill=col)

    # today's tally
    f_n = fonts.bold(34)
    f_lbl = fonts.regular(12)
    n = str(count_today)
    draw.text(((WIDTH - draw.textlength(n, font=f_n)) / 2, 196),
              n, font=f_n, fill=FG)
    lbl = "détection" + ("s" if count_today != 1 else "") + " aujourd'hui"
    draw.text(((WIDTH - draw.textlength(lbl, font=f_lbl)) / 2, 236),
              lbl, font=f_lbl, fill=FG_DIM)

    if last is not None:
        f_last = fonts.regular(11)
        txt = f"dernier : {last.common_name} · {last.clock}"
        while draw.textlength(txt, font=f_last) > WIDTH - 16 and len(txt) > 12:
            txt = txt[:-2]
        
        draw.text(((WIDTH - draw.textlength(txt, font=f_last)) / 2, 260),
                  txt, font=f_last, fill=FG_DIM)
    return frame


def render_selftest(fonts: Fonts) -> Image.Image:
    """
    Orientation / geometry probe. Every edge is labelled and the corners are
    marked, so a wrong offset_top or rotation is obvious at a glance.
    """
    frame = Image.new("RGB", (WIDTH, HEIGHT), (10, 10, 14))
    d = ImageDraw.Draw(frame)

    # 1px border: if any edge is clipped or wrapped, offsets are wrong.
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=(255, 255, 255))

    # RGB purity bars
    for i, c in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255),
                           (255, 255, 255), (128, 128, 128)]):
        d.rectangle([0, 30 + i * 16, WIDTH, 30 + i * 16 + 15], fill=c)

    f = fonts.bold(15)
    fs = fonts.regular(12)
    d.text((6, 6), "HAUT / TOP", font=f, fill=(255, 255, 255))
    bot = "BAS / BOTTOM"
    d.text((WIDTH - 6 - d.textlength(bot, font=f), HEIGHT - 22), bot,
           font=f, fill=(255, 255, 255))
    d.text((6, HEIGHT - 22), "L", font=f, fill=(255, 255, 0))
    d.text((WIDTH - 16, 6), "R", font=f, fill=(255, 255, 0))

    d.text((6, 120), f"{WIDTH} x {HEIGHT}", font=f, fill=(255, 255, 255))
    d.text((6, 142), "cercle = rond, pas ovale", font=fs, fill=(180, 180, 190))
    d.ellipse([70, 165, 170, 265], outline=(0, 255, 255), width=2)
    d.line([120, 165, 120, 265], fill=(0, 90, 90))
    d.line([70, 215, 170, 215], fill=(0, 90, 90))

    # corner markers
    for (cx, cy) in [(0, 0), (WIDTH - 8, 0), (0, HEIGHT - 8), (WIDTH - 8, HEIGHT - 8)]:
        d.rectangle([cx, cy, cx + 7, cy + 7], fill=(255, 0, 255))
    return frame


# =========================================================================
#  panel
# =========================================================================
def open_panel(args, log=True):
    """
    Bring up the TFT and return (panel, reset_request).

    The reset request MUST stay referenced for as long as the panel is used:
    releasing the gpiod line lets the pad fall low, which re-asserts the
    panel's active-low RES and blanks the display. This is also why rst is
    passed as None -- st7789 1.0.0 would otherwise pin RES low and never
    call reset(), holding the panel in permanent reset.
    """
    from nv3030b import NV3030B, hard_reset

    rst_req = hard_reset(args.rst)
    panel = NV3030B(
        port=0, cs=args.cs, dc=args.dc, backlight=args.backlight, rst=None,
        width=WIDTH, height=HEIGHT, rotation=args.rotation,
        invert=not args.no_invert, spi_speed_hz=args.spi_hz,
        offset_left=args.offset_left, offset_top=args.offset_top,
        bgr=not args.no_bgr,
    )
    if log:
        LOG.info(
            "NV3030B ready: %dx%d rot=%d offs=(%d,%d) invert=%s bgr=%s spi=%.1f MHz",
            WIDTH, HEIGHT, args.rotation, args.offset_left, args.offset_top,
            not args.no_invert, not args.no_bgr, args.spi_hz / 1e6,
        )
    # Clear once: the controller powers up with random RAM, which otherwise
    # shows as noise anywhere the first frame does not cover.
    panel.display(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)))
    return panel, rst_req


# =========================================================================
#  BirdNET-Go polling
# =========================================================================
class DetectionFeed:
    def __init__(self, api_base: str, timeout: float = 6.0):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self.online = False

    def recent(self, limit: int = 5) -> list[Detection]:
        url = f"{self.api_base}/api/v2/detections/recent"
        try:
            r = requests.get(url, params={"limit": limit}, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as e:
            if self.online:
                LOG.warning("BirdNET-Go unreachable: %s", e)
            self.online = False
            return []
        if not self.online:
            LOG.info("BirdNET-Go reachable")
        self.online = True
        if not isinstance(data, list):
            return []
        out = []
        for d in data:
            try:
                out.append(Detection.from_api(d))
            except (TypeError, ValueError):
                continue
        return out


# =========================================================================
#  main loop
# =========================================================================
class App:
    def __init__(self, args):
        self.args = args
        self.fonts = Fonts()
        self.feed = DetectionFeed(args.api)
        self.photos = PhotoStore(Path(args.cache_dir), args.api)
        self.disp = None
        self._rst_req = None   # must outlive the panel; see open_panel()
        self.stop = threading.Event()

        self.last_det: Detection | None = None
        self.seen_id = 0
        self.count_today = 0
        self.today = datetime.now().date()
        self.backlight_on = True
        self._redraw = queue.Queue(maxsize=4)
        # screen state machine: 0 = standby, 1 = today's species, 2 = system
        self.screen = 0
        self.n_screens = 3
        self.power_menu_until = 0.0
        self.button = None
        self._screen_drawn = 0.0
        self.listener = None
        self._listen_phase = 0
        self._listen_drawn = 0.0
        self._meter_drawn = 0.0
        # Single source of truth for the sleep timer. The previous code slept
        # relative to standby_at, which was only written when a detection
        # expired -- so waking via the button lit the panel and then slept
        # again on the very next iteration.
        self.last_activity = 0.0
        self.stream = None
        # A single deadline governs the whole bird frame, provisional and
        # confirmed alike. Two independent timers (one for the pending, one
        # for the confirmed detection) made the panel drop back to the info
        # screen in between, so the same bird appeared twice with a flash of
        # clock in the middle.
        self.bird_until = 0.0        # monotonic deadline, 0 = no bird shown
        self.bird_sci = ""           # scientific name currently on screen
        self.bird_confirmed = False  # has the confidence been filled in yet

    # --- hardware ---
    def open_display(self):
        self.disp, self._rst_req = open_panel(self.args)

    def show(self, image: Image.Image):
        if not self.backlight_on:
            self.disp.set_backlight(True)
            self.backlight_on = True
        self.disp.display(image)

    def sleep_screen(self):
        if self.backlight_on:
            LOG.info("backlight off (idle)")
            self.disp.set_backlight(False)
            self.backlight_on = False

    # --- detection handling ---
    def showing_bird(self, now: float) -> bool:
        return self.bird_until > now

    def _signal_led(self, seconds: float):
        """
        Tell the LED service to blink for `seconds`.

        A wall-clock deadline in a file, because the LED runs as a separate
        early-boot unit that must not depend on this one. Failures are
        ignored: a status light is never worth interrupting the display for.
        """
        try:
            os.makedirs(os.path.dirname(self.args.led_file), exist_ok=True)
            tmp = self.args.led_file + ".tmp"
            with open(tmp, "w") as f:
                f.write(str(time.time() + seconds))
            os.replace(tmp, self.args.led_file)
        except OSError as e:
            LOG.debug("led signal failed: %s", e)

    def present(self, det: Detection):
        """
        Draw a confirmed detection and run the display window from HERE.

        `hold` is deliberately counted from the moment the confidence appears,
        not from the provisional. BirdNET-Go holds a detection for
        export.length - export.precapture seconds (12 s at stock settings)
        before the REST API sees it, so a window started at the provisional
        would expire before the score ever arrived -- dropping back to the
        clock and then showing the same bird a second time.
        """
        now = time.monotonic()
        same = (self.bird_sci and det.scientific_name == self.bird_sci
                and self.showing_bird(now))
        photo = self.photos.get_cached(det.scientific_name)
        self.show(render_detection(det, photo, self.fonts))
        self.last_det = det
        self.last_activity = now
        self.bird_sci = det.scientific_name
        self.bird_confirmed = True
        self.bird_until = now + self.args.hold
        self._signal_led(self.args.hold)
        LOG.info("confirmed %s %.0f%% (%s) - on screen %.0fs",
                 det.common_name, det.confidence * 100,
                 "was provisional" if same else "new", self.args.hold)

        if photo is None and det.scientific_name:
            threading.Thread(
                target=self._fetch_then_redraw, args=(det,), daemon=True
            ).start()

    def _fetch_then_redraw(self, det: Detection):
        photo = self.photos.fetch(det.scientific_name)
        if photo is None or self.stop.is_set():
            return
        # Only upgrade if this detection is still the one on screen.
        if self.last_det is not None and self.last_det.id == det.id:
            try:
                self._redraw.put_nowait(det)
            except queue.Full:
                pass

    def run(self):
        self.open_display()
        self.last_activity = time.monotonic()
        self.show(render_standby(self.fonts, None, 0, False))

        if self.args.button_gpio > 0:
            b = Button(self.args.button_gpio, long_press_s=self.args.long_press)
            self.button = b if b.start() else None

        if self.args.sse:
            st = DetectionStream(self.args.api)
            self.stream = st if st.start() else None

        if self.args.listen:
            lm = LevelMonitor(device=self.args.listen_device,
                              trigger_db=self.args.listen_trigger)
            self.listener = lm if lm.start() else None

        # Seed the high-water mark so a restart doesn't replay old detections.
        for d in self.feed.recent(1):
            self.seen_id = max(self.seen_id, d.id)
        self.count_today = self._count_today()

        next_poll = 0.0
        while not self.stop.is_set():
            now = time.monotonic()

            # photo arrived for the detection currently on screen
            try:
                det = self._redraw.get_nowait()
                photo = self.photos.get_cached(det.scientific_name)
                if photo is not None and self.last_det and self.last_det.id == det.id:
                    self.show(render_detection(det, photo, self.fonts))
            except queue.Empty:
                pass

            # ---- pending detections over SSE ----
            # These land ~5 s before the REST API sees the same bird, because
            # the detection is still sitting in BirdNET-Go's pending map.
            while self.stream is not None:
                ev = self.stream.get()
                if ev is None:
                    break
                name, data = ev
                if name != "pending":
                    continue
                # The payload is a snapshot list of active pendings; an empty
                # list means BirdNET-Go has none left (confirmed or rejected).
                items = data if isinstance(data, list) else [data]
                active = [
                    it for it in items
                    if isinstance(it, dict)
                    and (it.get("status") or PENDING_ACTIVE) == PENDING_ACTIVE
                    and (it.get("species") or "").strip()
                ]
                # An EMPTY snapshot is deliberately ignored. It means the
                # pending has left BirdNET-Go's map, which happens both when
                # it is confirmed and when it is rejected - and the confirmed
                # detection is still a second away over the REST poll. Wiping
                # the screen here is what made the bird vanish and come back.
                if not active:
                    rejected = [
                        it for it in items if isinstance(it, dict)
                        and (it.get("status") or "") == PENDING_REJECTED
                        and (it.get("scientificName") or "").strip() == self.bird_sci
                    ]
                    if rejected and not self.bird_confirmed:
                        LOG.info("pending rejected: %s", self.bird_sci)
                        self.bird_until = 0.0
                        self.bird_sci = ""
                        self._force_screen(now)
                    continue
                # Newest first, so a burst shows the most recent candidate.
                active.sort(key=lambda it: it.get("lastUpdated") or 0)
                best = active[-1]
                species = best["species"].strip()
                sci = (best.get("scientificName") or "").strip()
                # Already showing this bird: leave the frame and its deadline
                # exactly as they are.
                if sci and sci == self.bird_sci and self.showing_bird(now):
                    continue
                # A confirmed frame outranks a pending for a different bird
                # only until its own time is up.
                if self.bird_confirmed and self.showing_bird(now):
                    continue
                LOG.info("pending: %s (%s)", species, sci)
                self.bird_sci = sci
                self.bird_confirmed = False
                # Only a safety net: it must outlast BirdNET-Go's flush delay
                # so the provisional is still up when the score lands. The
                # real display window starts in present().
                self.bird_until = now + self.args.provisional_max
                self.last_activity = now
                # Blink from the moment it is heard, matching the screen.
                self._signal_led(self.args.hold)
                self._show_provisional(now, species, sci)

            if now >= next_poll:
                next_poll = now + self.args.poll
                dets = self.feed.recent(5)
                fresh = sorted(
                    (d for d in dets if d.id > self.seen_id), key=lambda d: d.id
                )
                if fresh:
                    newest = fresh[-1]
                    self.seen_id = newest.id
                    if datetime.now().date() != self.today:
                        self.today = datetime.now().date()
                        self.count_today = 0
                    self.count_today += len(fresh)
                    LOG.info(
                        "detection #%d %s (%s) %.0f%%%s",
                        newest.id, newest.common_name, newest.scientific_name,
                        newest.confidence * 100,
                        "  [NEW]" if newest.is_new else "",
                    )
                    self.present(newest)

            # ---- button ----
            ev = self.button.get() if self.button is not None else None
            if ev:
                LOG.info("button %s press (screen=%d, power_menu=%s, awake=%s)",
                         ev, self.screen, bool(self.power_menu_until),
                         self.backlight_on)
                self.last_activity = now
            if ev == LONG_PRESS:
                if self.power_menu_until:
                    self.power_menu_until = 0.0      # long press cancels
                    self._force_screen(now)
                else:
                    self.power_menu_until = now + POWER_MENU_TIMEOUT
                    self.show(render_power_menu(self.fonts, POWER_MENU_TIMEOUT))
            elif ev == SHORT_PRESS:
                if self.power_menu_until:
                    LOG.info("power off confirmed via button")
                    self._poweroff()
                    continue
                # A press on a sleeping panel only wakes it; the next press
                # then starts cycling.
                # A press dismisses whatever bird is up and returns to the
                # info screens.
                self.bird_until = 0.0
                self.bird_sci = ""
                if not self.backlight_on:
                    LOG.info("waking panel")
                    self._force_screen(now)
                else:
                    self.screen = (self.screen + 1) % self.n_screens
                    self._force_screen(now)

            if self.power_menu_until:
                left = self.power_menu_until - now
                if left <= 0:
                    self.power_menu_until = 0.0
                    self._force_screen(now)
                elif now - self._screen_drawn > 0.9:
                    self._screen_drawn = now
                    self.show(render_power_menu(self.fonts, left))
                self.stop.wait(0.1)
                continue

            # ---- "heard something" while the recogniser is still pending ----
            # Only when no detection frame is currently held on screen: a real
            # result always outranks the provisional listening state.
            if (self.args.listen_screen and self.listener is not None
                    and not self.showing_bird(now)
                    and self.listener.active(self.args.listen_hold)):
                if now - self._listen_drawn > 1.1:
                    self._listen_drawn = now
                    self._listen_phase += 1
                    self.show(render_listening(
                        self.fonts, self.listener.level_db,
                        self.listener.floor_db, self._listen_phase))
                    self._screen_drawn = now
                self.stop.wait(0.2)
                continue

            # ---- wake on sound ----
            # Deliberately a higher bar than the header meter: the box is on
            # public display, and lighting up for every nearby conversation
            # would keep it awake all day. The noise floor is a rolling
            # percentile, so sustained talking raises it and stops
            # re-triggering by itself -- it is only a step ABOVE the ambient
            # that wakes the panel.
            if (self.args.wake_on_sound and self.listener is not None
                    and not self.backlight_on and not self.power_menu_until):
                over = self.listener.level_db - self.listener.floor_db
                if over >= self.args.wake_trigger:
                    LOG.info("waking on sound (+%.0f dB over floor %.0f dBFS)",
                             over, self.listener.floor_db)
                    self.last_activity = now
                    self.bird_until = 0.0
                    self.bird_sci = ""
                    self._force_screen(now)

            # ---- discrete level meter in the header ----
            # A partial write, so this can refresh several times a second
            # without the cost (or the visual noise) of a full redraw. Only on
            # the info screens: over a detection photo there is no gradient
            # background to repaint the tile against.
            if (self.listener is not None and not self.showing_bird(now)
                    and not self.power_menu_until and self.backlight_on
                    and now - self._meter_drawn > self.args.meter_interval):
                self._meter_drawn = now
                self._push_meter()

            # ---- the bird's single display window expires ----
            if self.bird_until and now > self.bird_until:
                self.bird_until = 0.0
                self.bird_confirmed = False
                self._force_screen(
                    now, why=f"window over for {self.bird_sci or '?'}")
                self.bird_sci = ""

            if not self.showing_bird(now):
                idle = now - self.last_activity
                if self.args.sleep_after > 0 and idle > self.args.sleep_after:
                    self.sleep_screen()
                elif self.backlight_on and now - self._screen_drawn > 20:
                    self._force_screen(now)

            self.stop.wait(0.5)

        self.shutdown()


    def _show_provisional(self, now: float, species: str, sci: str):
        det = Detection(id=0, common_name=species, scientific_name=sci,
                        confidence=0.0,
                        clock=datetime.now().strftime("%H:%M"), is_new=False)
        photo = self.photos.get_cached(sci)
        self.show(render_detection(det, photo, self.fonts, provisional=True))
        self._screen_drawn = now
        if photo is None and sci:
            threading.Thread(target=self._fetch_then_redraw,
                             args=(det,), daemon=True).start()

    def _meter_values(self):
        """(dB above the rolling floor, whether that counts as an onset)."""
        if self.listener is None:
            return None, False
        over = max(0.0, self.listener.level_db - self.listener.floor_db)
        return over, over >= self.args.listen_trigger

    def _push_meter(self):
        """Repaint just the meter rectangle."""
        over, hot = self._meter_values()
        if over is None:
            return
        try:
            self.disp.display_region(render_meter_tile(over, hot),
                                     METER_X, METER_Y)
        except Exception as e:
            # A driver without partial-write support must not kill the loop;
            # the meter simply refreshes with the next full redraw instead.
            LOG.debug("meter partial write unavailable: %s", e)
            self.args.meter_interval = 1e9

    def _force_screen(self, now=None, why=""):
        """Draw whichever info screen is currently selected."""
        now = time.monotonic() if now is None else now
        if why:
            LOG.info("info screen (%s)", why)
        self._screen_drawn = now
        over, hot = self._meter_values()
        if self.screen == 1:
            self.show(render_species_today(
                self.fonts, self._species_today(), self.count_today,
                over_db=over, hot=hot))
        elif self.screen == 2:
            self.show(render_sysinfo(self.fonts, self._sysinfo(),
                                     over_db=over, hot=hot))
        else:
            self.show(render_standby(
                self.fonts, self.last_det, self.count_today, self.feed.online,
                over_db=over, hot=hot))
        self._meter_drawn = now

    # --- screen data ---
    def _species_today(self):
        """Aggregate today's detections by species, most frequent first."""
        try:
            r = requests.get(f"{self.args.api}/api/v2/detections/recent",
                             params={"limit": 100}, timeout=6)
            r.raise_for_status()
            rows = r.json()
        except Exception:
            return []
        today = datetime.now().strftime("%Y-%m-%d")
        agg = {}
        for d in rows if isinstance(rows, list) else []:
            if d.get("date") and d["date"] != today:
                continue
            name = (d.get("commonName") or "?").strip()
            n, best = agg.get(name, (0, 0.0))
            agg[name] = (n + 1, max(best, float(d.get("confidence") or 0)))
        return sorted(((k, v[0], v[1]) for k, v in agg.items()),
                      key=lambda t: (-t[1], t[0]))

    def _sysinfo(self):
        import shutil, socket, subprocess
        out = []

        ip = "-"
        try:
            sk = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sk.connect(("192.0.2.1", 1))   # no traffic, just picks the route
            ip = sk.getsockname()[0]
            sk.close()
        except Exception:
            pass
        out.append(("adresse IP", ip, FG))

        try:
            with open("/proc/loadavg") as f:
                load = f.read().split()[0]
            out.append(("charge CPU", load, FG))
        except Exception:
            pass

        temp = None
        try:
            temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0
            col = CONF_HIGH if temp < 65 else (CONF_MED if temp < 75 else CONF_LOW)
            out.append(("température", f"{temp:.0f} °C", col))
        except Exception:
            pass

        try:
            with open("/proc/meminfo") as f:
                mi = {a.split(":")[0]: a.split()[1] for a in f if ":" in a}
            used = (int(mi["MemTotal"]) - int(mi["MemAvailable"])) / 1024
            tot = int(mi["MemTotal"]) / 1024
            out.append(("mémoire", f"{used:.0f}/{tot:.0f} Mo", FG))
        except Exception:
            pass

        try:
            du = shutil.disk_usage("/")
            out.append(("disque libre", f"{du.free/1e9:.1f} Go", FG))
        except Exception:
            pass

        try:
            up = float(open("/proc/uptime").read().split()[0])
            h, m = int(up // 3600), int((up % 3600) // 60)
            out.append(("en marche", f"{h} h {m:02d}", FG))
        except Exception:
            pass

        # Undervoltage is the failure mode this box is prone to; surface it.
        try:
            t = subprocess.run(["/usr/bin/vcgencmd", "get_throttled"],
                               capture_output=True, text=True, timeout=3).stdout
            v = int(t.strip().split("=")[1], 16)
            if v & 0x1:
                out.append(("ALIMENTATION", "sous-tension !", CONF_LOW))
            elif v & 0x10000:
                out.append(("alimentation", "ok (alerte passée)", CONF_MED))
            else:
                out.append(("alimentation", "ok", CONF_HIGH))
        except Exception:
            pass

        out.append(("BirdNET-Go", "en ligne" if self.feed.online else "hors ligne",
                    CONF_HIGH if self.feed.online else CONF_LOW))
        return out

    def _poweroff(self):
        import subprocess
        self.show(render_shutting_down(self.fonts))
        time.sleep(1.2)
        for cmd in (["sudo", "-n", "/usr/bin/systemctl", "poweroff"],
                    ["systemctl", "poweroff"]):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                if r.returncode == 0:
                    self.stop.set()
                    return
                LOG.warning("%s failed: %s", cmd[0], r.stderr.strip()[:120])
            except Exception as e:
                LOG.warning("%s error: %s", cmd[0], e)
        LOG.error("could not power off - is the sudoers rule installed?")

    def _count_today(self) -> int:
        try:
            r = requests.get(
                f"{self.args.api}/api/v2/detections",
                params={"date": datetime.now().strftime("%Y-%m-%d"),
                        "limit": 1, "numResults": 1},
                timeout=6,
            )
            if r.ok:
                j = r.json()
                if isinstance(j, dict) and "total" in j:
                    return int(j["total"])
        except Exception:
            pass
        return 0

    def shutdown(self):
        LOG.info("shutting down")
        if self.button is not None:
            self.button.stop()
        if self.listener is not None:
            self.listener.stop()
        if self.stream is not None:
            self.stream.stop()
        try:
            if self.disp is not None:
                self.disp.display(Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0)))
                self.disp.set_backlight(False)
        except Exception as e:
            LOG.warning("clean shutdown failed: %s", e)


# =========================================================================
def build_args(argv=None):
    def envint(k, d):
        return int(os.environ.get(k, d))

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default=os.environ.get("PIOU_API", "http://127.0.0.1:8080"))
    p.add_argument("--cache-dir", default=os.environ.get("PIOU_CACHE", "/var/lib/piou/imgcache"))
    p.add_argument("--poll", type=float, default=float(os.environ.get("PIOU_POLL", 0.5)),
                   help="seconds between API polls")
    p.add_argument("--hold", type=float, default=float(os.environ.get("PIOU_HOLD", 10)),
                   help="seconds the bird stays on screen once its confidence "
                        "is known")
    p.add_argument("--led-file", default=os.environ.get(
                       "PIOU_LED_BLINK_FILE", "/run/piou/led-blink-until"),
                   help="where to write the LED blink deadline")
    p.add_argument("--provisional-max", type=float,
                   default=float(os.environ.get("PIOU_PROV_MAX", 30.0)),
                   help="safety cap on an unconfirmed provisional; must exceed "
                        "BirdNET-Go's export.length - export.precapture")
    p.add_argument("--sleep-after", type=float, default=float(os.environ.get("PIOU_SLEEP", 600)),
                   help="seconds of standby before the backlight turns off (0 = never)")
    # wiring, per the build: DC=GPIO24, RES=GPIO25, BLK=GPIO22, CS=CE0
    p.add_argument("--dc", type=int, default=envint("PIOU_DC", 24))
    p.add_argument("--rst", type=int, default=envint("PIOU_RST", 25))
    p.add_argument("--backlight", type=int, default=envint("PIOU_BL", 22))
    p.add_argument("--cs", type=int, default=envint("PIOU_CS", 0))
    p.add_argument("--rotation", type=int, choices=[0, 180],
                   default=envint("PIOU_ROT", 0),
                   help="only 0/180 are valid for a non-square panel")
    p.add_argument("--offset-left", type=int, default=envint("PIOU_OFFL", 0))
    p.add_argument("--offset-top", type=int, default=envint("PIOU_OFFT", 20),
                   help="240x280 panels sit 20 rows into the ST7789's 240x320 RAM")
    p.add_argument("--spi-hz", type=int, default=envint("PIOU_SPI_HZ", 8_000_000))
    p.add_argument("--no-invert", action="store_true",
                   help="send INVOFF (0x20) instead of INVON (0x21)")
    p.add_argument("--listen", action="store_true", default=True,
                   help="watch the mic level and show a 'heard something' screen")
    p.add_argument("--no-listen", dest="listen", action="store_false")
    p.add_argument("--listen-device", default=os.environ.get("PIOU_LISTEN_DEV", "birdmic"))
    p.add_argument("--listen-trigger", type=float,
                   default=float(os.environ.get("PIOU_LISTEN_TRIG", 9.0)),
                   help="dB above the rolling noise floor that counts as an onset")
    p.add_argument("--sse", action="store_true", default=True,
                   help="subscribe to the pending-detection stream so the "
                        "species appears ~5s before the REST API has it")
    p.add_argument("--no-sse", dest="sse", action="store_false")
    p.add_argument("--wake-on-sound", action="store_true", default=True,
                   help="light the panel when the mic hears something loud")
    p.add_argument("--no-wake-on-sound", dest="wake_on_sound",
                   action="store_false")
    p.add_argument("--wake-trigger", type=float,
                   default=float(os.environ.get("PIOU_WAKE_TRIG", 15.0)),
                   help="dB above the rolling floor needed to wake the panel; "
                        "higher than --listen-trigger on purpose")
    p.add_argument("--listen-screen", action="store_true",
                   help="take over the whole screen on an onset instead of "
                        "just lighting the header meter (noisy in public)")
    p.add_argument("--meter-interval", type=float,
                   default=float(os.environ.get("PIOU_METER", 0.35)),
                   help="seconds between header level-meter refreshes")
    p.add_argument("--listen-hold", type=float,
                   default=float(os.environ.get("PIOU_LISTEN_HOLD", 12.0)),
                   help="seconds to keep the listening screen after an onset")
    p.add_argument("--button-gpio", type=int, default=envint("PIOU_BUTTON", 21),
                   help="GPIO for the push button to GND (0 disables)")
    p.add_argument("--long-press", type=float,
                   default=float(os.environ.get("PIOU_LONGPRESS", 2.0)),
                   help="seconds held to open the power menu")
    p.add_argument("--no-bgr", action="store_true",
                   help="clear MADCTL's BGR bit; this panel needs it SET")
    p.add_argument("--hold-oneshot", type=float, default=0,
                   help="with --selftest/--demo, keep the panel driven N seconds")
    p.add_argument("--selftest", action="store_true",
                   help="draw a geometry/colour test pattern and exit")
    p.add_argument("--demo", action="store_true",
                   help="render a fake detection and exit (no BirdNET-Go needed)")
    p.add_argument("--save", metavar="PNG",
                   help="also write the rendered frame to a PNG (works headless)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = build_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )
    fonts = Fonts()

    # --- one-shot modes ---
    if args.selftest or args.demo:
        if args.selftest:
            frame = render_selftest(fonts)
        else:
            det = Detection(
                id=1, common_name="Rougequeue à front blanc",
                scientific_name="Phoenicurus phoenicurus",
                confidence=0.87, clock=datetime.now().strftime("%H:%M"),
                is_new=True,
            )
            store = PhotoStore(Path(args.cache_dir), args.api)
            photo = store.get_cached(det.scientific_name) or store.fetch(det.scientific_name)
            frame = render_detection(det, photo, fonts)
        if args.save:
            frame.save(args.save)
            LOG.info("wrote %s", args.save)
        try:
            disp, _rst_req = open_panel(args)
            disp.display(frame)
            LOG.info("frame sent to panel")
            if args.hold_oneshot:
                LOG.info("holding for %.0fs", args.hold_oneshot)
                time.sleep(args.hold_oneshot)
        except Exception as e:
            LOG.error("could not drive the panel: %s", e)
            return 0 if args.save else 1
        return 0

    app = App(args)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: app.stop.set())
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
