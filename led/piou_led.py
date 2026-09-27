#!/usr/bin/env python3
"""
Breathing status LED for the PiouPiou box: lit means the Pi is up.

GPIO 26 has no hardware PWM (only 12/13/18/19 do), so this drives the kernel's
software PWM instead of toggling the pin from Python. The `pwm-gpio` overlay
exposes an hrtimer-timed channel under /sys/class/pwm, which is what keeps the
fade free of the flicker a userspace toggle loop produces -- this process only
rewrites a duty cycle 50 times a second, while the kernel handles the timing.

Brightness is gamma-corrected. An LED's perceived brightness is roughly the
2.2 power of its duty cycle, so a linear ramp looks like it lingers at the top
and snaps off at the bottom; raising the sine to that power makes the breath
look even.
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import signal
import sys
import time

PWM_CLASS = "/sys/class/pwm"
DRIVER = "pwm-gpio"

# The display service writes a unix-epoch deadline here when it puts a bird on
# screen; this process blinks until that time passes. A file rather than a
# socket or an SSE subscription of its own, deliberately: this unit starts
# before the network and before BirdNET-Go, and must never gain a dependency
# that could keep the "box is alive" light dark.
BLINK_FILE = "/run/piou/led-blink-until"


def find_chip(driver: str = DRIVER) -> str | None:
    """
    Locate the pwmchip belonging to the software-PWM driver.

    Not hardcoded to pwmchip0: enabling any other PWM overlay (audio, a fan)
    renumbers the chips, and driving the wrong one would silently do nothing.
    """
    for chip in sorted(glob.glob(f"{PWM_CLASS}/pwmchip*")):
        link = os.path.join(chip, "device", "driver")
        try:
            if os.path.basename(os.path.realpath(link)) == driver:
                return chip
        except OSError:
            continue
    return None


def _write(path: str, value) -> None:
    with open(path, "w") as f:
        f.write(str(value))


class Breather:
    def __init__(self, period_hz: int, cycle_s: float, floor: float,
                 gamma: float, step_s: float, blink_hz: float = 4.0,
                 blink_file: str = BLINK_FILE):
        self.period_ns = int(1e9 / period_hz)
        self.cycle_s = cycle_s
        self.floor = floor
        self.gamma = gamma
        self.step_s = step_s
        self.blink_hz = blink_hz
        self.blink_file = blink_file
        self.chip: str | None = None
        self.duty = None
        self.running = True

    # ---- device ----
    def open_pwm(self) -> bool:
        chip = find_chip()
        if chip is None:
            return False
        ch = os.path.join(chip, "pwm0")
        if not os.path.isdir(ch):
            try:
                _write(os.path.join(chip, "export"), 0)
            except OSError as e:
                print(f"export failed: {e}", file=sys.stderr, flush=True)
                return False
            # The kernel creates the channel directory asynchronously.
            for _ in range(50):
                if os.path.isdir(ch):
                    break
                time.sleep(0.05)
            else:
                return False
        try:
            # Order matters: a duty above the new period is rejected, so zero
            # it before changing the period.
            _write(os.path.join(ch, "duty_cycle"), 0)
            _write(os.path.join(ch, "period"), self.period_ns)
            _write(os.path.join(ch, "enable"), 1)
        except OSError as e:
            print(f"pwm setup failed: {e}", file=sys.stderr, flush=True)
            return False
        self.chip, self.duty = chip, open(os.path.join(ch, "duty_cycle"), "w")
        print(f"breathing on {chip} "
              f"({1e9/self.period_ns:.0f} Hz, {self.cycle_s}s cycle)", flush=True)
        return True

    def close_pwm(self, off: bool = True):
        if self.duty is None or self.chip is None:
            return
        try:
            if off:
                self.duty.write("0")
                self.duty.flush()
                _write(os.path.join(self.chip, "pwm0", "enable"), 0)
        except OSError:
            pass
        try:
            self.duty.close()
        except OSError:
            pass
        self.duty = None

    # ---- modes ----
    def blink_deadline(self) -> float:
        """Epoch time until which to blink, or 0. Missing file is normal."""
        try:
            with open(self.blink_file) as f:
                return float(f.read().strip() or 0)
        except (OSError, ValueError):
            return 0.0

    def brightness(self, t: float) -> float:
        raw = (1 - math.cos(2 * math.pi * (t % self.cycle_s) / self.cycle_s)) / 2
        return self.floor + (1.0 - self.floor) * raw ** self.gamma

    def blink_brightness(self, t: float) -> float:
        """Hard square wave: unmistakably different from the slow breath."""
        return 1.0 if (t * self.blink_hz) % 1.0 < 0.5 else 0.0

    def run(self):
        # The overlay may not have probed yet when this starts, which is the
        # normal case for an early-boot unit: wait rather than exit and let
        # systemd thrash on restarts.
        waited = 0.0
        while self.running and not self.open_pwm():
            if waited == 0.0:
                print("waiting for the pwm-gpio device...", flush=True)
            time.sleep(0.5)
            waited += 0.5
            if waited > 120:
                print("pwm-gpio never appeared - is "
                      "'dtoverlay=pwm-gpio,gpio=26' in config.txt?",
                      file=sys.stderr, flush=True)
                return 1

        t0 = time.monotonic()
        blinking = False
        last_check = 0.0
        deadline = 0.0
        while self.running:
            now = time.monotonic()
            # Re-read the deadline a few times a second, not every step.
            if now - last_check > 0.25:
                last_check = now
                deadline = self.blink_deadline()
            want_blink = deadline > time.time()
            if want_blink != blinking:
                blinking = want_blink
                t0 = now          # restart the waveform on a mode change
                print("blink" if blinking else "breathe", flush=True)

            b = (self.blink_brightness(now - t0) if blinking
                 else self.brightness(now - t0))
            try:
                self.duty.write(str(int(b * self.period_ns)))
                self.duty.flush()
            except OSError as e:
                # Device went away (overlay unloaded); re-acquire rather than die.
                print(f"pwm write failed ({e}), reopening", flush=True)
                self.close_pwm(off=False)
                if not self.open_pwm():
                    time.sleep(1.0)
                    continue
                t0 = time.monotonic()
            time.sleep(self.step_s)
        self.close_pwm()
        return 0

    def stop(self, *_):
        self.running = False


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hz", type=int, default=int(os.environ.get("PIOU_LED_HZ", 400)),
                   help="PWM frequency; higher is smoother but costs kernel time")
    p.add_argument("--cycle", type=float,
                   default=float(os.environ.get("PIOU_LED_CYCLE", 4.0)),
                   help="seconds for one full breath")
    p.add_argument("--floor", type=float,
                   default=float(os.environ.get("PIOU_LED_FLOOR", 0.02)),
                   help="minimum brightness, so it never fully extinguishes")
    p.add_argument("--gamma", type=float,
                   default=float(os.environ.get("PIOU_LED_GAMMA", 2.2)),
                   help="perceptual correction; 1.0 is a raw linear ramp")
    p.add_argument("--blink-hz", type=float,
                   default=float(os.environ.get("PIOU_LED_BLINK_HZ", 4.0)),
                   help="blink rate while a detection is on screen")
    p.add_argument("--blink-file", default=os.environ.get(
                       "PIOU_LED_BLINK_FILE", BLINK_FILE),
                   help="file holding a unix-epoch deadline to blink until")
    p.add_argument("--step", type=float,
                   default=float(os.environ.get("PIOU_LED_STEP", 0.02)),
                   help="seconds between duty updates")
    a = p.parse_args()

    b = Breather(a.hz, a.cycle, a.floor, a.gamma, a.step,
                 blink_hz=a.blink_hz, blink_file=a.blink_file)
    signal.signal(signal.SIGTERM, b.stop)
    signal.signal(signal.SIGINT, b.stop)
    return b.run()


if __name__ == "__main__":
    sys.exit(main())
