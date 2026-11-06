#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
images=$1
python3 - "$project/.build" <<'PY'
from pathlib import Path
import socket,sys
for path in Path(sys.argv[1]).glob('qemu*.qmp'):
    connection=socket.socket(socket.AF_UNIX)
    connection.settimeout(1)
    try: connection.connect(str(path))
    except OSError: pass
    else: raise SystemExit('Stop project QEMU before overwriting dist images, or use PIPLAYER_SKIP_PACKAGE=1 and package-source.sh for documentation only.')
    finally: connection.close()
PY
python3 "$project/scripts/check-image.py" "$images/sdcard.img" --boot-dir "$images"
mkdir -p "$project/dist/boot"
cp "$images/sdcard.img" "$project/dist/piplayer-rpi4.img"
cp "$images/Image" "$images/bcm2711-rpi-4-b.dtb" "$project/dist/boot/"
xz -T2 -1 -k -f "$project/dist/piplayer-rpi4.img"
(cd "$project/dist" && sha256sum piplayer-rpi4.img piplayer-rpi4.img.xz > SHA256SUMS)
if [[ -f "$project/.local/public-mode" ]]; then
  # Do not distribute generated build credentials with an image whose access
  # is set individually at first boot. Existing files may belong to another
  # build, so leave them untouched and make their status explicit.
  if [[ -e "$project/dist/admin_ed25519" || -e "$project/dist/credentials.json" ]]; then
    echo 'Public image: existing access files in dist are from another build and do not apply.' >&2
  fi
else
  install -m 600 "$project/.local/admin_ed25519" "$project/dist/admin_ed25519"
  install -m 600 "$project/.local/credentials.json" "$project/dist/credentials.json"
fi
"$project/scripts/package-source.sh"
if [[ -f "$project/.local/public-mode" ]]; then
  echo 'Public image is in dist/; configure individual access before first boot.'
else
  echo 'Image and private access credentials are in dist/.'
fi
