#!/usr/bin/env python3
"""
piou_precache -- pre-download every species photo the range filter expects,
so the TFT panel works with no internet.

BirdNET-Go's range filter already knows which species are plausible at the
configured coordinates and week, so that list -- not the full 6500-species
model label set -- is what needs caching. Each photo is stored as a
ready-to-blit 240x280 JPEG in the same cache the display reads.

The work is resumable and polite: species already cached are skipped, species
with no upstream photo are recorded so reruns don't ask again, and requests
are spaced out because each cache miss makes BirdNET-Go fetch from an
upstream provider (Avicommons / Wikimedia) on our behalf.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, "/opt/piou/display")
from piou_display import PhotoStore, slugify  # noqa: E402

STOP = False


def _on_signal(*_):
    global STOP
    STOP = True
    print("\n  interrupted -- finishing current item, progress is kept", flush=True)


def fetch_species(api: str, timeout: float = 20.0) -> list[dict]:
    """
    Species the range filter considers plausible here.

    Falls back to the full species picker if the range endpoint is missing,
    which would be a much larger download but is better than nothing.
    """
    for path, key in (
        ("/api/v2/range/species/list", "species"),
        ("/api/v2/species/all", None),
    ):
        try:
            r = requests.get(api.rstrip("/") + path, timeout=timeout)
        except requests.RequestException as e:
            print(f"  {path}: {e}")
            continue
        if not r.ok:
            print(f"  {path}: HTTP {r.status_code}")
            continue
        try:
            data = r.json()
        except ValueError:
            continue
        rows = data.get(key, []) if (key and isinstance(data, dict)) else data
        if isinstance(rows, list) and rows:
            if path.startswith("/api/v2/range"):
                loc = data.get("location", {})
                print(f"  range filter: {data.get('count', len(rows))} species "
                      f"at lat={loc.get('latitude')} lon={loc.get('longitude')} "
                      f"threshold={data.get('threshold')}")
            else:
                print(f"  full species list: {len(rows)} species")
            return [r_ for r_ in rows if isinstance(r_, dict)]
    return []


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api", default="http://127.0.0.1:8080")
    p.add_argument("--cache-dir", default="/var/lib/piou/imgcache")
    p.add_argument("--delay", type=float, default=2.0,
                   help="seconds between species that need a network fetch")
    p.add_argument("--limit", type=int, default=0,
                   help="stop after N newly cached photos (0 = no limit)")
    p.add_argument("--retries", type=int, default=5,
                   help="attempts per species while BirdNET-Go resolves it")
    p.add_argument("--dry-run", action="store_true",
                   help="only report what is missing")
    args = p.parse_args(argv)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    # Species with no upstream photo at all: remembered so a rerun is cheap.
    missing_file = cache / "_no_photo.json"
    try:
        known_missing = set(json.loads(missing_file.read_text()))
    except Exception:
        known_missing = set()

    print("fetching species list...")
    species = fetch_species(args.api)
    if not species:
        print("ERROR: could not obtain a species list -- is BirdNET-Go running?")
        return 1

    store = PhotoStore(cache, args.api)

    todo = []
    have = 0
    for sp in species:
        sci = (sp.get("scientificName") or "").strip()
        if not sci:
            continue
        if store.path_for(sci).exists():
            have += 1
        elif sci in known_missing:
            pass
        else:
            todo.append((sci, (sp.get("commonName") or "").strip()))

    print(f"\n  already cached : {have}")
    print(f"  known photoless: {len(known_missing)}")
    print(f"  to fetch       : {len(todo)}")
    est = len(todo) * args.delay / 60.0
    print(f"  estimated time : {est:.0f} min at {args.delay}s spacing\n")

    if args.dry_run:
        for sci, common in todo[:40]:
            print(f"    {sci}  ({common})")
        if len(todo) > 40:
            print(f"    ... and {len(todo) - 40} more")
        return 0

    ok = failed = 0
    for i, (sci, common) in enumerate(todo, 1):
        if STOP:
            break
        if args.limit and ok >= args.limit:
            print(f"  reached --limit {args.limit}")
            break

        img = store.fetch(sci, attempts=args.retries)
        if img is not None:
            ok += 1
            status = "ok"
        elif sci in store._missing:
            known_missing.add(sci)
            missing_file.write_text(json.dumps(sorted(known_missing), indent=0))
            status = "no photo"
            failed += 1
        else:
            status = "failed (will retry next run)"
            failed += 1

        print(f"  [{i}/{len(todo)}] {sci:38s} {common[:22]:24s} {status}", flush=True)

        # Space out only real network work; cache hits cost nothing upstream.
        if not STOP and i < len(todo):
            time.sleep(args.delay)

    total = len(list(cache.glob("*.jpg")))
    size_mb = sum(f.stat().st_size for f in cache.glob("*.jpg")) / 1e6
    print(f"\ndone: {ok} newly cached, {failed} unavailable")
    print(f"cache now holds {total} photos ({size_mb:.1f} MB) in {cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
