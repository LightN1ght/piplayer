#!/usr/bin/env python3
"""Upload atomically through SFTP; the worker validates the completed file."""
import argparse
from pathlib import Path
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('video', type=Path)
parser.add_argument('--host', default='192.168.50.1')
parser.add_argument('--port', type=int, default=22)
parser.add_argument('--user', default='player')
parser.add_argument('--key', type=Path, default=ROOT / '.local/admin_ed25519')
args = parser.parse_args()
video = args.video.resolve()
if not video.is_file():
    parser.error(f'File not found: {video}')
if args.host.startswith('-') or any(c in args.host for c in '\r\n @'):
    parser.error('Invalid host')
if not args.user.isalnum():
    parser.error('Invalid user')
if not args.key.is_file():
    parser.error('Administration key not found; pass --key dist/admin_ed25519')
if any(c in str(video) for c in '\r\n'):
    parser.error('Newlines are not supported in filenames')
quoted_video = '"' + str(video).replace('\\', '\\\\').replace('"', '\\"') + '"'
token = uuid.uuid4().hex
remote = f'/data/incoming/{token}'
batch = f'put {quoted_video} {remote}.part\nchmod 644 {remote}.part\nrename {remote}.part {remote}.ready.mp4\n'
known_hosts = ROOT / '.local/known_hosts'
known_hosts.parent.mkdir(exist_ok=True, mode=0o700)
known_hosts_option = str(known_hosts).replace('\\', '\\\\').replace('"', '\\"')
command = ['sftp', '-b', '-', '-P', str(args.port), '-i', str(args.key),
           '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
           '-o', 'StrictHostKeyChecking=accept-new',
           '-o', f'UserKnownHostsFile="{known_hosts_option}"', f'{args.user}@{args.host}']
try:
    subprocess.run(command, input=batch, text=True, check=True)
except subprocess.CalledProcessError:
    print('Upload failed. A partial .part file may remain in /data/incoming; it is never played.')
    raise SystemExit(1)
print('Upload complete. Watch the player page; the device will validate and activate the video.')

