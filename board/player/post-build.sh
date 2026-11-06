#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
target=$1
if [ ! -e "$target/bin/stat" ] && [ ! -e "$target/usr/bin/stat" ]; then
  echo 'PiPlayer requires BusyBox stat with FEATURE_STAT_FORMAT; check busybox.fragment.' >&2
  exit 1
fi
install -d "$target/etc/player" "$target/root/.ssh" "$target/data/.ssh" "$target/data/media" "$target/data/incoming" "$target/run/player" "$target/usr/share/player/vendor"
install -m 600 "$project/.local/player.conf" "$target/etc/player/player.conf"
install -m 600 "$project/.local/admin_ed25519.pub" "$target/root/.ssh/authorized_keys"
install -m 600 "$project/.local/admin_ed25519.pub" "$target/data/.ssh/authorized_keys"
chmod 700 "$target/data/.ssh"
chmod 700 "$target/root/.ssh"
grep -q -- '-c /usr/bin/playerd' "$target/etc/inittab" || \
  printf '%s\n' '::respawn:/bin/su -s /bin/sh player -c /usr/bin/playerd' >> "$target/etc/inittab"
# Root is password-locked, but can use the separately delivered administration key.
sed -i 's/^root:[^:]*:/root:*:/' "$target/etc/shadow"
install -m 644 "$project/vendor/hls.light.min.js" "$target/usr/share/player/vendor/hls.light.min.js"
install -m 644 "$project/vendor/hls.LICENSE" "$target/usr/share/player/vendor/hls.LICENSE"
# AP setup owns dnsmasq; the packaged init would start it a second time.
rm -f "$target/etc/init.d/S80dnsmasq"
find "$target/etc/init.d" -type f -name '*hostapd*' -delete
# BusyBox hotplug loads brcmfmac; explicit loading is also done by AP setup.
printf '%s\n' 'brcmfmac' > "$target/etc/modules"
chown -R 1000:1000 "$target/data" 2>/dev/null || true

