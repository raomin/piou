"""
Single push-button input for the PiouPiou panel.

One GPIO plus ground: the button shorts the pin to GND and the internal
pull-up provides the idle level, so no external resistor is needed.

A short press cycles screens; a long press opens the power menu. Presses are
delivered as events on a queue so the render loop never blocks on input, and
the poll runs in its own thread at a fine interval because the main loop ticks
far too slowly to time a press.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

LOG = logging.getLogger("piou.button")

SHORT_PRESS = "short"
LONG_PRESS = "long"


class Button:
    def __init__(self, gpio: int = 21, chip: str = "/dev/gpiochip0",
                 long_press_s: float = 2.0, debounce_s: float = 0.05,
                 poll_s: float = 0.02):
        self.gpio = gpio
        self.chip = chip
        self.long_press_s = long_press_s
        self.debounce_s = debounce_s
        self.poll_s = poll_s
        self.events: queue.Queue[str] = queue.Queue(maxsize=8)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._req = None
        self._gpiod_value_inactive = None

    def start(self) -> bool:
        try:
            import errno
            import gpiod
            from gpiod.line import Bias, Direction, Value
            self._gpiod_value_inactive = Value.INACTIVE
            settings = gpiod.LineSettings(
                direction=Direction.INPUT, bias=Bias.PULL_UP)
            # A restart can race the old process releasing the line (EBUSY).
            for _ in range(20):
                try:
                    self._req = gpiod.request_lines(
                        self.chip, consumer="piou-button",
                        config={self.gpio: settings})
                    break
                except OSError as e:
                    if e.errno != errno.EBUSY:
                        raise
                    time.sleep(0.25)
            if self._req is None:
                LOG.warning("button GPIO%d still busy, running without it",
                            self.gpio)
                return False
        except Exception as e:
            LOG.warning("button on GPIO%d unavailable: %s", self.gpio, e)
            return False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        LOG.info("button ready on GPIO%d (to GND, internal pull-up)", self.gpio)
        return True

    def _pressed(self) -> bool:
        # Wired to GND, so a press reads INACTIVE (low).
        return self._req.get_value(self.gpio) == self._gpiod_value_inactive

    def _loop(self):
        while not self._stop.is_set():
            if not self._pressed():
                self._stop.wait(self.poll_s)
                continue

            # Debounce, then confirm it is still down.
            time.sleep(self.debounce_s)
            if not self._pressed():
                continue

            t0 = time.monotonic()
            fired_long = False
            while self._pressed() and not self._stop.is_set():
                if not fired_long and time.monotonic() - t0 >= self.long_press_s:
                    # Fire as soon as the threshold passes, so the user gets
                    # feedback while still holding rather than on release.
                    self._emit(LONG_PRESS)
                    fired_long = True
                time.sleep(self.poll_s)
            if not fired_long:
                self._emit(SHORT_PRESS)
            # Ignore contact bounce on release.
            time.sleep(self.debounce_s)

    def _emit(self, kind: str):
        try:
            self.events.put_nowait(kind)
        except queue.Full:
            pass

    def get(self) -> str | None:
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self._req is not None:
            try:
                self._req.release()
            except Exception:
                pass
