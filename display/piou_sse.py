"""
Server-sent-events client for BirdNET-Go's detection stream.

Why this exists: a detection is held in BirdNET-Go's pending map for
`export.length - export.precapture` seconds (5 s at our settings) before it
reaches the database, and the REST API only sees it after that. But the
species is already known the moment the pending is created, and BirdNET-Go
publishes exactly that over SSE as a `pending` event -- the same feed its own
dashboard uses for a "currently hearing" card.

Subscribing lets the panel name the bird about five seconds earlier than
polling ever could.

Only `pending` is consumed here. The confirmed `detection` event carries a
payload shaped by detectionPayloadForClient(), whose field names differ from
the REST DTO; rather than guess them, the existing REST poll stays the source
of truth for the final frame. So SSE buys latency without becoming a second
place where the detection schema has to be tracked.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time

import requests

LOG = logging.getLogger("piou.sse")

PENDING_ACTIVE = "active"
PENDING_REJECTED = "rejected"


class DetectionStream:
    def __init__(self, api_base: str, timeout: float = 70.0):
        # Heartbeats arrive every ~15 s, so a read timeout comfortably above
        # that distinguishes a dead connection from an idle one.
        self.url = api_base.rstrip("/") + "/api/v2/detections/stream"
        self.timeout = timeout
        self.events: queue.Queue[tuple[str, object]] = queue.Queue(maxsize=32)
        self.connected = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        self._thread = threading.Thread(target=self._supervise, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    # ---- connection ----
    def _supervise(self):
        backoff = 1.0
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._read_stream()
            except requests.RequestException as e:
                LOG.debug("detection stream: %s", e)
            except Exception as e:
                LOG.warning("detection stream error: %s", e)
            self.connected = False
            if self._stop.is_set():
                break
            # Only a connection that actually lasted counts as healthy.
            if time.monotonic() - started > 30:
                backoff = 1.0
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)

    def _read_stream(self):
        headers = {"Accept": "text/event-stream", "Cache-Control": "no-cache"}
        with requests.get(self.url, headers=headers, stream=True,
                          timeout=(5.0, self.timeout)) as r:
            r.raise_for_status()
            if not self.connected:
                LOG.info("subscribed to detection stream")
            self.connected = True
            event = None
            for raw in r.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    return
                if raw is None:
                    continue
                line = raw.strip()
                if not line:
                    event = None          # blank line terminates an event
                    continue
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:") and event:
                    payload = line[5:].strip()
                    if event == "heartbeat":
                        continue
                    try:
                        data = json.loads(payload)
                    except ValueError:
                        continue
                    # `pending` arrives as []SSEPendingDetection -- a snapshot
                    # of every currently-active pending, where an empty array
                    # means "nothing pending any more". `detection` is an
                    # object. Pass both through and let the consumer decide.
                    if isinstance(data, (dict, list)):
                        self._emit(event, data)

    def _emit(self, event: str, data):
        try:
            self.events.put_nowait((event, data))
        except queue.Full:
            pass

    def get(self) -> tuple[str, object] | None:
        try:
            return self.events.get_nowait()
        except queue.Empty:
            return None
