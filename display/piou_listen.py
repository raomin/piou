"""
Local audio level monitor, so the panel can react to sound immediately.

BirdNET-Go holds every detection in a pending map for realtime.interval
seconds before it reaches the API, so the panel cannot learn "something is
happening" from the detection feed without that delay baked in. This watches
the microphone directly and fires as soon as the level rises above the
rolling background, which lets the UI say "j'ai entendu quelque chose" while
the recogniser is still thinking.

The ALSA config exposes the mic through dsnoop, so reading it here does not
take the device away from BirdNET-Go.

Audio is read from `arecord` rather than a Python ALSA binding to avoid
another native dependency; the subprocess is supervised and restarted if it
dies.
"""

from __future__ import annotations

import collections
import logging
import math
import subprocess
import threading
import time

import numpy as np

LOG = logging.getLogger("piou.listen")

FLOOR_PERCENTILE = 25     # background estimate, robust to bursts
MIN_FLOOR_DBFS = -85.0    # never chase the floor below the mic's noise


class LevelMonitor:
    """
    Rolling RMS of the capture device, with a self-calibrating noise floor.

    `triggered_at` is the monotonic time of the most recent onset, so callers
    can decide how long to keep showing a "listening" state.
    """

    def __init__(self, device: str = "birdmic", rate: int = 48000,
                 chunk_s: float = 0.2, trigger_db: float = 9.0,
                 floor_window_s: float = 20.0, retrigger_s: float = 2.0):
        self.device = device
        self.rate = rate
        self.chunk_frames = max(1, int(rate * chunk_s))
        self.trigger_db = trigger_db
        self.retrigger_s = retrigger_s
        self._floor_hist = collections.deque(
            maxlen=max(4, int(floor_window_s / chunk_s)))
        # Need a representative sample of the background before judging onsets.
        self._warmup = max(4, self._floor_hist.maxlen // 4)
        self.level_db = -120.0
        self.floor_db = MIN_FLOOR_DBFS
        self.triggered_at = 0.0
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle ----
    def start(self) -> bool:
        self._thread = threading.Thread(target=self._supervise, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self._kill_proc()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _kill_proc(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    # ---- capture ----
    def _spawn(self):
        cmd = ["arecord", "-D", self.device, "-f", "S16_LE",
               "-r", str(self.rate), "-c", "1", "-t", "raw", "-q"]
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)

    def _supervise(self):
        backoff = 1.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._spawn()
                LOG.info("level monitor reading %s", self.device)
                self._read_loop()
            except Exception as e:
                LOG.warning("level monitor error: %s", e)
            # Only treat a run that actually lasted as healthy; a spawn that
            # dies immediately must back off instead of hot-looping.
            if time.monotonic() - started > 30:
                backoff = 1.0
            self._kill_proc()
            if self._stop.is_set():
                break
            # The device can be briefly unavailable while BirdNET-Go restarts.
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _read_exact(self, n: int) -> bytes | None:
        """
        Read exactly n bytes.

        stdout is an unbuffered raw pipe, where read(n) legitimately returns
        fewer than n bytes. Only a zero-length read means the child is gone,
        so short reads must be accumulated rather than treated as EOF.
        """
        assert self._proc is not None and self._proc.stdout is not None
        chunks, got = [], 0
        while got < n and not self._stop.is_set():
            b = self._proc.stdout.read(n - got)
            if not b:
                return None                  # genuine EOF: child exited
            chunks.append(b)
            got += len(b)
        return b"".join(chunks) if got == n else None

    def _read_loop(self):
        nbytes = self.chunk_frames * 2      # S16 mono
        while not self._stop.is_set():
            buf = self._read_exact(nbytes)
            if buf is None:
                err = b""
                try:
                    if self._proc is not None and self._proc.stderr is not None:
                        err = self._proc.stderr.read() or b""
                except Exception:
                    pass
                raise RuntimeError(
                    f"arecord exited: {err.decode(errors='replace').strip()[:200]}")
            samples = np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(samples * samples)))
            self.level_db = 20.0 * math.log10(max(rms, 1e-9))
            self._update(self.level_db)

    # ---- onset detection ----
    def _update(self, level_db: float):
        self._floor_hist.append(level_db)
        if len(self._floor_hist) >= 4:
            self.floor_db = max(
                MIN_FLOOR_DBFS,
                float(np.percentile(np.array(self._floor_hist), FLOOR_PERCENTILE)),
            )
        # Until enough history has accumulated, floor_db is still the
        # MIN_FLOOR_DBFS placeholder, and every real sample sits far above it.
        # Triggering during that window produces a guaranteed false onset in
        # the first seconds after every restart.
        if len(self._floor_hist) < self._warmup:
            return

        now = time.monotonic()
        if (level_db > self.floor_db + self.trigger_db
                and now - self.triggered_at > self.retrigger_s):
            self.triggered_at = now
            LOG.info("onset: %.1f dBFS over floor %.1f dBFS",
                      level_db, self.floor_db)

    def active(self, hold_s: float) -> bool:
        """True while an onset is recent enough to keep the UI in listening mode."""
        return self.triggered_at > 0 and (
            time.monotonic() - self.triggered_at) < hold_s
