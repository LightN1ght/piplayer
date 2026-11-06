#!/usr/bin/env python3
"""Check the raw SD image's real size, MBR layout and filesystem signatures."""
import argparse
import hashlib
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('image', type=Path)
parser.add_argument('--boot-dir', type=Path, help='Also compare supplied QEMU kernel/DTB with the real FAT files')
args = parser.parse_args()
size = args.image.stat().st_size
if not 0 < size <= 480_000_000:
    raise SystemExit(f'Image does not fit the size budget: {size} bytes')
with args.image.open('rb') as image:
    mbr = image.read(512)
    if mbr[510:512] != b'\x55\xaa':
        raise SystemExit('Invalid MBR signature')
    disk_signature = struct.unpack_from('<I', mbr, 440)[0]
    if disk_signature != 0x504c4159:
        raise SystemExit(f'Unexpected MBR disk signature: {disk_signature:08x}; expected 504c4159')
    previous_end = 512
    for index, expected in enumerate((0x0C, 0x83)):
        partition = mbr[446 + index * 16:462 + index * 16]
        kind = partition[4]
        start, length = struct.unpack_from('<II', partition, 8)
        offset, end = start * 512, (start + length) * 512
        if kind != expected or offset < previous_end or end > size or not length:
            raise SystemExit(f'Invalid partition {index + 1}')
        previous_end = end
        image.seek(offset)
        if index == 0:
            boot = image.read(512)
            if boot[510:512] != b'\x55\xaa' or boot[82:90] != b'FAT32   ':
                raise SystemExit('Boot partition must be FAT32')
            # Read the actual FAT32 file, without mounting or host mtools.
            sector_size = struct.unpack_from('<H', boot, 11)[0]
            sectors_per_cluster = boot[13]
            reserved = struct.unpack_from('<H', boot, 14)[0]
            fat_sectors = struct.unpack_from('<I', boot, 36)[0]
            root_cluster = struct.unpack_from('<I', boot, 44)[0]
            if sector_size not in (512, 1024, 2048, 4096) or sectors_per_cluster == 0:
                raise SystemExit('Invalid FAT32 geometry')
            cluster_size = sector_size * sectors_per_cluster
            fat_start = offset + reserved * sector_size
            data_start = offset + (reserved + boot[16] * fat_sectors) * sector_size

            def chain(cluster):
                seen = set()
                while 2 <= cluster < 0x0ffffff8:
                    if cluster in seen or len(seen) >= length * 512 // cluster_size:
                        raise SystemExit('Invalid FAT32 cluster chain')
                    seen.add(cluster)
                    position = data_start + (cluster - 2) * cluster_size
                    if position < data_start or position + cluster_size > end:
                        raise SystemExit('FAT32 cluster is outside the boot partition')
                    image.seek(position)
                    yield image.read(cluster_size)
                    image.seek(fat_start + cluster * 4)
                    cluster = struct.unpack('<I', image.read(4))[0] & 0x0fffffff

            cmdline = None
            for directory in chain(root_cluster):
                for position in range(0, len(directory), 32):
                    entry = directory[position:position + 32]
                    if entry[:11] == b'CMDLINE TXT' and entry[11] != 0x0f:
                        first = struct.unpack_from('<H', entry, 26)[0] | struct.unpack_from('<H', entry, 20)[0] << 16
                        file_size = struct.unpack_from('<I', entry, 28)[0]
                        if file_size > 4096:
                            raise SystemExit('Unexpectedly large cmdline.txt')
                        cmdline = b''.join(chain(first))[:file_size].decode('ascii').split()
                        break
                if cmdline is not None:
                    break
            roots = [argument for argument in cmdline or [] if argument.startswith('root=')]
            expected_root = f'root=PARTUUID={disk_signature:08x}-02'
            if roots != [expected_root]:
                raise SystemExit(f'Boot/root mismatch: {roots}; expected {expected_root}')
            print(f'Boot command line matches PARTUUID {disk_signature:08x}-02')
            if args.boot_dir:
                candidates = [shutil.which('mcopy'),
                              args.boot_dir.parent / 'host/bin/mcopy',
                              Path(__file__).resolve().parents[1] / '.build/tools/usr/bin/mcopy']
                mcopy = next((str(path) for path in candidates if path and Path(path).is_file()), None)
                if mcopy is None:
                    raise SystemExit('mcopy is required for --boot-dir verification')
                with tempfile.TemporaryDirectory(prefix='piplayer-boot-check-') as directory:
                    for name in ('Image', 'bcm2711-rpi-4-b.dtb'):
                        extracted = Path(directory) / name
                        subprocess.run([mcopy, '-i', f'{args.image}@@{offset}', f'::{name}', str(extracted)], check=True)
                        with extracted.open('rb') as source:
                            actual_hash = hashlib.file_digest(source, 'sha256').digest()
                        with (args.boot_dir / name).open('rb') as source:
                            expected_hash = hashlib.file_digest(source, 'sha256').digest()
                        if actual_hash != expected_hash:
                            raise SystemExit(f'QEMU boot file does not match raw FAT: {name}')
                print('Kernel and DTB match the files inside the raw image')
        else:
            image.seek(offset + 1024 + 56)
            if image.read(2) != b'\x53\xef':
                raise SystemExit('Root partition is not ext4')
        print(f'Partition {index + 1}: type=0x{kind:02x}, offset={offset}, bytes={length * 512}')
with args.image.open('rb') as image:
    digest = hashlib.file_digest(image, 'sha256').hexdigest()
print(f'PASS: {size} bytes ({size / 1_000_000:.2f} MB); SHA256 {digest}')
