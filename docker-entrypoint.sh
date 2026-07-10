#!/bin/sh
# kHUB Docker entrypoint
set -e
chown -R khub:khub /data 2>/dev/null || true
exec dumb-init python3 -m khub.cli "$@"
