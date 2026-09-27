"""
NV3030B TFT controller support, built on top of the st7789 Python driver.

The NV3030B shares the ST7789's addressing commands (CASET 0x2A, RASET 0x2B,
RAMWR 0x2C, MADCTL 0x36, COLMOD 0x3A), so all of the pixel-pushing plumbing in
the st7789 package -- SPI setup, gpiod pin handling, set_window() with offsets,
and image_to_data() -- is reusable. Only the power-on register sequence
differs, so that is the single thing overridden here.

Two workarounds live in this module:

1. st7789 1.0.0 never calls reset(): its constructor requests the RES line as
   an output with output_value=INACTIVE and then goes straight to _init(),
   leaving the panel in permanent hardware reset so every command is ignored.
   hard_reset() below performs a correct reset pulse and *keeps* the gpiod
   request alive, so RES stays de-asserted for as long as the caller holds it.
   Always construct the panel with rst=None and drive reset through here.

2. The register sequence is cross-checked against two independent references
   (CircuitPython circuitpython_NV3030B and STM32_Lib_TFT_NV3030B). They agree
   on every register except MADCTL's BGR bit, which is panel-dependent, so it
   is exposed as `bgr` rather than baked in.
"""

from __future__ import annotations

import errno
import time

import gpiod
from gpiod.line import Direction, Value
from st7789 import ST7789

# 240x280 NV3030B panels show a window starting 20 rows into the
# controller's 240x320 RAM (XSTART=0, YSTART=20).
OFFSET_TOP_240X280 = 20
OFFSET_LEFT_240X280 = 0

MADCTL = 0x36
MADCTL_BGR = 0x08
COLMOD = 0x3A
INVON = 0x21
INVOFF = 0x20
SLPOUT = 0x11
DISPON = 0x29
TEON = 0x35

# (command, data bytes, delay_ms). Vendor "private access" registers 0x60-0x68
# and 0xb1-0xf6 set bias, pump, VCOM, frame rate, porch and gamma; they are
# only writable between the 0xfd unlock and re-lock pairs.
_INIT: list[tuple[int, list[int], int]] = [
    (0xFD, [0x06, 0x08], 0),                      # unlock private registers
    (0x61, [0x07, 0x04], 0),
    (0x62, [0x00, 0x44, 0x45], 0),                # bias
    (0x63, [0x41, 0x07, 0x12, 0x12], 0),
    (0x64, [0x37], 0),
    (0x65, [0x09, 0x10, 0x21], 0),                # VSP charge pump
    (0x66, [0x09, 0x10, 0x21], 0),                # VSN charge pump
    (0x67, [0x20, 0x40], 0),                      # pump select
    (0x68, [0x90, 0x4C, 0x7C, 0x66], 0),          # gamma vap/van + VCOM
    (0xB1, [0x0F, 0x02, 0x01], 0),                # frame rate
    (0xB4, [0x01], 0),                            # 1-dot inversion
    (0xB5, [0x02, 0x02, 0x0A, 0x14], 0),          # blanking porch
    (0xB6, [0x04, 0x01, 0x9F, 0x00, 0x02], 0),
    (0xDF, [0x11], 0),
    (0xE2, [0x13, 0x00, 0x00, 0x30, 0x33, 0x3F], 0),
    (0xE5, [0x3F, 0x33, 0x30, 0x00, 0x00, 0x13], 0),
    (0xE1, [0x00, 0x57], 0),
    (0xE4, [0x58, 0x00], 0),
    (0xE0, [0x01, 0x03, 0x0E, 0x0E, 0x0C, 0x15, 0x19], 0),   # +gamma
    (0xE3, [0x1A, 0x16, 0x0C, 0x0F, 0x0E, 0x0D, 0x02, 0x01], 0),  # -gamma
    (0xE6, [0x00, 0xFF], 0),
    (0xE7, [0x01, 0x04, 0x03, 0x03, 0x00, 0x12], 0),
    (0xE8, [0x00, 0x70, 0x00], 0),
    (0xEC, [0x52], 0),
    (0xF1, [0x01, 0x01, 0x02], 0),
    (0xF6, [0x09, 0x10, 0x00, 0x00], 0),
    (0xFD, [0xFA, 0xFC], 0),                      # re-lock
    (COLMOD, [0x05], 0),                          # 16bpp RGB565
    (TEON, [0x00], 0),
]


def hard_reset(rst_gpio: int = 25, chip: str = "/dev/gpiochip0",
               consumer: str = "piou-nv3030b-rst"):
    """
    Pulse RES correctly and return the gpiod request holding it de-asserted.

    The caller MUST keep the returned object referenced for as long as the
    panel is in use: releasing the line lets the pad fall back to low, which
    re-asserts reset and blanks the display.
    """
    # On a service restart the dying process may not have released this line
    # yet, which surfaces as EBUSY. Retry briefly instead of failing the whole
    # service and relying on systemd to win the race on the next attempt.
    settings = gpiod.LineSettings(
        direction=Direction.OUTPUT, output_value=Value.ACTIVE)
    last = None
    for attempt in range(20):
        try:
            req = gpiod.request_lines(
                chip, consumer=consumer, config={rst_gpio: settings})
            break
        except OSError as e:
            last = e
            if e.errno != errno.EBUSY:
                raise
            time.sleep(0.25)
    else:
        raise RuntimeError(
            f"GPIO{rst_gpio} still held after 5 s: {last}") from last
    req.set_value(rst_gpio, Value.ACTIVE)    # de-asserted
    time.sleep(0.05)
    req.set_value(rst_gpio, Value.INACTIVE)  # assert reset
    time.sleep(0.05)
    req.set_value(rst_gpio, Value.ACTIVE)    # release
    time.sleep(0.15)                         # datasheet wants >=120 ms
    return req


class NV3030B(ST7789):
    """
    An NV3030B panel driven through the st7789 package's plumbing.

    Construct with rst=None and call hard_reset() first, keeping its return
    value alive. `bgr` flips MADCTL's colour-order bit for panels whose
    subpixel order is reversed.
    """

    def __init__(self, *args, bgr: bool = True, madctl_extra: int = 0x00, **kwargs):
        self._bgr = bgr
        self._madctl_extra = madctl_extra
        if kwargs.get("rst") is not None:
            raise ValueError(
                "pass rst=None and use hard_reset(); st7789 1.0.0 would "
                "otherwise pin RES low and hold the panel in reset"
            )
        super().__init__(*args, **kwargs)

    def display_region(self, image, x: int, y: int):
        """
        Write a sub-rectangle only.

        A full 240x280 frame is ~134 KB, about 134 ms at 8 MHz, which is far
        too slow to animate a small live indicator. Addressing just the dirty
        rectangle makes a header-sized tile cost well under 2 ms.

        image_to_data() is size-agnostic, but it applies numpy.rot90 for
        rotation, which would also need the rectangle's coordinates
        transformed. Only rotation 0 is handled here; anything else must fall
        back to a full display() by the caller.
        """
        if self._rotation != 0:
            raise ValueError("display_region supports rotation 0 only")
        w, h = image.size
        if w <= 0 or h <= 0:
            return
        if x < 0 or y < 0 or x + w > self._width or y + h > self._height:
            raise ValueError(
                f"region {w}x{h} at ({x},{y}) outside {self._width}x{self._height}")
        self.set_window(x, y, x + w - 1, y + h - 1)
        self.send(self.image_to_data(image, 0), True)

    def _init(self):
        madctl = self._madctl_extra | (MADCTL_BGR if self._bgr else 0x00)
        self.command(MADCTL)
        self.data(madctl)

        for cmd, payload, delay_ms in _INIT:
            self.command(cmd)
            for b in payload:
                self.data(b)
            if delay_ms:
                time.sleep(delay_ms / 1000.0)

        self.command(INVON if self._invert else INVOFF)
        self.command(SLPOUT)
        time.sleep(0.200)
        self.command(DISPON)
        time.sleep(0.020)
