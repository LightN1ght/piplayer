#!/usr/bin/env bash
set -euo pipefail
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
qemu=${QEMU_SYSTEM_AARCH64:-qemu-system-aarch64}
if ! command -v "$qemu" >/dev/null && [[ -x "$project/.build/tools/usr/bin/qemu-system-aarch64" ]]; then
  qemu="$project/.build/tools/usr/bin/qemu-system-aarch64"
fi
image=${PIPLAYER_IMAGE:-$project/dist/piplayer-rpi4.img}
ssh_port=${PIPLAYER_SSH_PORT:-2222}
http_port=${PIPLAYER_HTTP_PORT:-8080}
qmp_socket=${PIPLAYER_QMP_SOCKET:-$project/.build/qemu.qmp}
machine=${PIPLAYER_QEMU_MACHINE:-virt}
reset=0
for option in "$@"; do
  case "$option" in
    --reset) reset=1 ;;
    --raspi4|--raspi4b) machine=raspi4b ;;
    --virt) machine=virt ;;
    *) echo "Usage: $0 [--reset] [--virt|--raspi4]" >&2; exit 1 ;;
  esac
done
case "$machine" in virt|raspi4b) ;; *) echo 'Unsupported QEMU machine' >&2; exit 1 ;; esac
mkdir -p "$project/.build"
[[ -f "$image" ]] || { echo "Build the image first: scripts/build.sh" >&2; exit 1; }
python3 "$project/scripts/check-image.py" "$image" >/dev/null
overlay="$project/.build/qemu-$machine.qcow2"
base_hash="$project/.build/qemu-$machine-base.sha256"
dtb="$project/.build/qemu-rpi4.dtb"
image_hash=$(sha256sum "$image" | cut -d ' ' -f 1)
if [[ "$reset" == 1 ]]; then
  if [[ -S "$qmp_socket" ]] && python3 - "$qmp_socket" <<'PY'
import socket,sys
s=socket.socket(socket.AF_UNIX)
s.settimeout(1)
try: s.connect(sys.argv[1])
except OSError: raise SystemExit(1)
else: raise SystemExit(0)
PY
  then echo 'Stop the existing project VM before --reset.' >&2; exit 1; fi
  rm -f "$overlay" "$base_hash"
  if [[ -f "$project/.local/known_hosts" ]]; then
    ssh-keygen -R "[127.0.0.1]:$ssh_port" -f "$project/.local/known_hosts" >/dev/null 2>&1 || true
  fi
fi
if [[ -f "$overlay" ]] && { [[ ! -f "$base_hash" ]] || [[ "$(cat "$base_hash")" != "$image_hash" ]]; }; then
  echo 'Raw image changed or overlay provenance is unknown. Stop QEMU, then run scripts/run-qemu.sh --reset (discards test VM data).' >&2
  exit 1
fi
if [[ ! -f "$overlay" ]]; then
  # QEMU's SD model requires a power-of-two capacity. The distributable raw
  # image remains below 480,000,000 bytes; this virtual overlay is not flashed.
  qemu-img create -q -f qcow2 -F raw -b "$image" "$overlay" 512M
  printf '%s\n' "$image_hash" > "$base_hash"
fi
net="user,id=net0,hostfwd=tcp:127.0.0.1:$ssh_port-:22,hostfwd=tcp:127.0.0.1:$http_port-:8080"
if [[ "$machine" == virt ]]; then
  # The same Pi kernel/rootfs also has builtin VirtIO drivers. This avoids the
  # raspi4b model's slow USB NIC during video/network service testing.
  exec "$qemu" -M virt,gic-version=2 -cpu cortex-a72 -m 1G -smp 4 \
    -display none -serial mon:stdio \
    -qmp "unix:$qmp_socket,server=on,wait=off" \
    -kernel "$project/dist/boot/Image" \
    -drive "file=$overlay,format=qcow2,if=none,id=sdcard" -device virtio-blk-device,drive=sdcard \
    -append 'console=ttyAMA0,115200 root=PARTUUID=504c4159-02 rootfstype=ext4 rootwait rw' \
    -netdev "$net" -device virtio-net-device,netdev=net0
fi
command -v fdtput >/dev/null || { echo 'Install device-tree-compiler (fdtput/fdtget).' >&2; exit 1; }
cp "$project/dist/boot/bcm2711-rpi-4-b.dtb" "$dtb"
# Direct kernel boot does not apply config.txt firmware overlays.
fdtput -t s "$dtb" /soc/usb@7e980000 status okay
fdtput -t s "$dtb" /soc/usb@7e980000 dr_mode host
fdtput -t s "$dtb" /soc/serial@7e201000 status okay
fdtput -t s "$dtb" /soc/serial@7e201000/bluetooth status disabled
aux_uart=$(fdtget "$dtb" /aliases serial0)
fdtput -t s "$dtb" /aliases serial0 /soc/serial@7e201000
fdtput -t s "$dtb" /aliases serial1 "$aux_uart"
exec "$qemu" -M raspi4b -m 2G -smp 4 -display none -serial mon:stdio \
  -qmp "unix:$qmp_socket,server=on,wait=off" \
  -kernel "$project/dist/boot/Image" -dtb "$dtb" \
  -drive "file=$overlay,format=qcow2,if=sd" \
  -append 'earlycon=pl011,mmio32,0xfe201000 console=ttyAMA0,115200 root=PARTUUID=504c4159-02 rootfstype=ext4 rootwait rw' \
  -netdev "$net" \
  -device usb-net,netdev=net0

