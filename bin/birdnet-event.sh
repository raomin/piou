#!/bin/sh
# Event sink for BirdNET-Go's "script" push-notification provider.
#
# BirdNET-Go runs this with the notification exported both as environment
# variables and as a JSON document on stdin (input_format: both). We append
# the JSON to a newline-delimited log so anything else on the box can tail a
# stable, structured event stream.
#
# Note: the built-in detection notification only fires for *new* species.
# The TFT display therefore reads every detection from the local API instead;
# this file is the durable event record and a hook point for other consumers.

SPOOL=/var/lib/piou/events.jsonl
MAXBYTES=1048576   # rotate at 1 MiB, keep one previous file

payload=$(cat)
[ -n "$payload" ] || payload=$(printf '{"type":"%s","title":"%s","message":"%s"}' \
    "${NOTIFICATION_TYPE:-}" "${NOTIFICATION_TITLE:-}" "${NOTIFICATION_MESSAGE:-}")

printf '%s\n' "$payload" >> "$SPOOL"

size=$(stat -c %s "$SPOOL" 2>/dev/null || echo 0)
[ "$size" -gt "$MAXBYTES" ] && mv -f "$SPOOL" "$SPOOL.1"

exit 0
