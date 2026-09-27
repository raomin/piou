# PiouPiou

**A self-contained bird detector in a box.** A Raspberry Pi listens to the
garden around the clock, identifies every song with BirdNET, and shows the
bird — photo, French name, Latin name, time and confidence — on a small
display. One button cycles the screens; an LED breathes while the box is
alive and blinks when it hears something.

> 🇫🇷 **The full step-by-step build guide is in French: [`doc-fr/README.md`](doc-fr/README.md).**
> It's written Instructables-style for makers — every step says what you need,
> what to do, and how to verify it worked, with the traps flagged along the way.
> This page is the English overview.

---

## What it does

- **Listens continuously** through an I2S MEMS microphone — no USB sound card.
- **Identifies** each call with [BirdNET-Go](https://github.com/tphakala/birdnet-go),
  filtered to the ~220 species plausible at your location and time of year.
- **Shows the bird within 3–4 seconds** of the call. The display subscribes to
  BirdNET-Go's live *pending* stream, so it names the species before the
  detection is even written to the database (~12 s earlier than polling).
- **Works offline.** Photos for every regional species are pre-fetched and
  refreshed monthly as migration changes the plausible set.
- **Three screens** — waiting (clock, tally, live level meter), today's
  species, system status — and a **long-press power menu** for clean shutdown.
- **Sleeps** after 10 minutes of quiet and **wakes on sound** or a press.
- BirdNET-Go's full web UI stays available on port 8080.

## Hardware

| | |
|---|---|
| Computer | Raspberry Pi 3 Model B (rev 1.2), 1 GB — a Pi 4 would give more headroom |
| Microphone | INMP441 I2S MEMS breakout |
| Display | 1.69″ IPS 240×280, 42 × 41 mm module, **NV3030B** controller (some sell as ST7789V3 — same pinout, different init) |
| Input | Momentary push button with built-in LED |
| Power | **5 V ≥ 2.5 A of genuine quality** — see the guide; this was the #1 source of problems |
| Cooling | Passive heatsink (required) |
| Enclosure | 3 mm MDF, laser cut from the parametric file in `box/` |

Software: Raspberry Pi OS Lite 64-bit (Debian 13), BirdNET-Go `20260823`, Python 3.13.

## How the pieces fit

```
  INMP441 ──I2S──▶ ALSA "birdmic" ──┬──▶ BirdNET-Go ──▶ SQLite / web UI :8080
   (mic)          (+24 dB, mono,    │        │
                   shared dsnoop)   │        ├─ SSE "pending" ──▶ piou_display ──▶ NV3030B TFT
                                    │        └─ REST /recent ───▶     │              240×280
                                    └──▶ level monitor ────────▶     │
                                         (wake on sound, meter)      ├─ button (GPIO21)
                                                                     └─ /run/piou/led-blink-until
                                                                              │
                                                              piou_led ◀──────┘──▶ LED (GPIO26, kernel PWM)
```

Three systemd services plus a timer. The LED service starts ~6 s after
power-on and depends on nothing else, so a lit LED genuinely means "alive".

## Repository layout

```
README.md                  this overview (EN)
doc-fr/README.md           the full build guide (FR)
display/                   the display application and its NV3030B driver
led/                       status LED daemon
bin/                       photo pre-cache, event hook
systemd/                   service and timer units
config/                    asound.conf, config.txt block, BirdNET-Go settings, sudoers
box/                       parametric laser-cut enclosure (piou_box.py → piou_box.svg)
todo.md                    the original brief the project started from
```

Every value in the guide — pin numbers, thresholds, timings, the bugs — comes
from the actual build, not from datasheets.

## Things worth knowing before you start

These are the findings that cost the most time. They're all covered properly
in the guide's troubleshooting section.

- **Power.** Two USB chargers and two cables failed on this Pi 3 — not for lack
  of watts, but because cable resistance plus NEON inference transients dipped
  below the 4.63 V brown-out threshold. A bench supply on the GPIO 5 V pins
  fixed it. `vcgencmd get_throttled` is the first thing to check when anything
  is slow or flaky.
- **The `st7789` 1.0.0 Python library never calls `reset()`**, leaving the
  panel in permanent reset. Two perfectly good panels were suspected before
  `pinctrl get 25` revealed the reset line held low. `display/nv3030b.py`
  works around it.
- **BirdNET-Go can only select ALSA devices that carry a `hint` block**, and
  its default `sysdefault` isn't one of them. `arecord` working proves nothing.
- **BirdNET-Go's stock `privacyfilter.confidence: 0.05`** discards every
  detection in any window with a 5 % chance of human speech — which, in an
  occupied room, is nearly always. Raised to 0.7.
- **Detection latency is set by `export.length − precapture`** (12 s at stock),
  not by `realtime.interval`. The display sidesteps it entirely via the SSE
  pending stream, so clip length and screen speed are decoupled.

## Credits

- [BirdNET-Go](https://github.com/tphakala/birdnet-go) by Tomi P. Hakala, built
  on the BirdNET model from the Cornell Lab of Ornithology and TU Chemnitz.
- [`st7789`](https://github.com/pimoroni/st7789-python) by Pimoroni for the SPI
  and gpiod plumbing.
- NV3030B init sequence cross-checked against
  [`circuitpython_NV3030B`](https://github.com/emsignailgnehs/circuitpython_NV3030B)
  and [`STM32_Lib_TFT_NV3030B`](https://github.com/GolinskiyKonstantin/STM32_Lib_TFT_NV3030B).
- Bird photos via BirdNET-Go's image proxy (Avicommons / Wikimedia Commons).

## License

*Choose one before publishing — MIT is a good fit for a hardware/software
build like this. Note that BirdNET-Go and the BirdNET model carry their own
licenses (the model is CC BY-NC-SA 4.0, i.e. non-commercial).*
