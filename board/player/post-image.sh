#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
install -m 644 "$project/board/player/cmdline.txt" "$BINARIES_DIR/cmdline.txt"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
genimage --rootpath "$tmp" --tmppath "$BUILD_DIR/genimage.tmp" \
  --inputpath "$BINARIES_DIR" --outputpath "$BINARIES_DIR" \
  --config "$project/board/player/genimage.cfg"
bytes=$(stat -c %s "$BINARIES_DIR/sdcard.img")
[ "$bytes" -le 480000000 ] || { echo "Image exceeds 480 MB: $bytes" >&2; exit 1; }
sha256sum "$BINARIES_DIR/sdcard.img" > "$BINARIES_DIR/sdcard.img.sha256"

