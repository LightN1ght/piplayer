#!/usr/bin/env python3
"""Exercise address-based presentation on an already booted two-NIC test VM.

This changes the VM configuration, uploads media and optionally reboots it.
It is not a test of physical ingress interfaces or Wi-Fi radio hardware.
"""
import argparse
import http.client
import json
import math
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--still-port', type=int, default=8082)
parser.add_argument('--video-port', type=int, default=8083)
parser.add_argument('--ssh-port', type=int, default=2225)
parser.add_argument('--key', type=Path, default=ROOT / '.local/admin_ed25519')
parser.add_argument('--reboot', action='store_true')
args = parser.parse_args()
if args.host.startswith('-') or any(c in args.host for c in '\r\n @'):
    parser.error('Invalid host')
known = str(ROOT / '.local/known_hosts').replace('\\', '\\\\').replace('"', '\\"')
common = ['-i', str(args.key), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
          '-o', 'StrictHostKeyChecking=accept-new', '-o', f'UserKnownHostsFile="{known}"']
ssh = ['ssh', '-p', str(args.ssh_port), *common, f'root@{args.host}']
video = ROOT / '.build/demo.mp4'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def remote(command, data=None, check=True):
    result = subprocess.run(ssh + [command], input=data, text=True, capture_output=True, timeout=20)
    if check and result.returncode:
        raise RuntimeError(f'SSH command failed ({result.returncode}): {result.stderr.strip()}')
    return result


def get(port, path='/', headers=None):
    request = urllib.request.Request(f'http://{args.host}:{port}{path}', headers=headers or {})
    try:
        response = opener.open(request, timeout=5)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, dict(response.headers.items()), response.read()


def header(headers, name):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


def wait_until(predicate, description, timeout=90):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            last = str(exc)
        time.sleep(1)
    raise RuntimeError(f'Timeout waiting for {description}: {last}')


def mode(port, expected):
    code, headers, body = get(port)
    return code == 200 and header(headers, 'X-PiPlayer-Mode') == expected and (
        b'id="picture"' in body if expected == 'still' else b'<video' in body)


def wait_mode(port, expected, timeout=45):
    wait_until(lambda: mode(port, expected), f'{expected} on {port}', timeout)


def set_mode(value, iface):
    # The original config is restored in finally; appending preserves other settings.
    remote(f"printf '\\nINTERFACE_MODES={value}\\nSTILL_INTERFACES={iface}\\n' >> /etc/player/player.conf")


def status(port):
    code, headers, body = get(port, '/status.json')
    if code != 200:
        raise RuntimeError(f'status.json returned {code}')
    return header(headers, 'X-PiPlayer-Mode'), json.loads(body)


def manifest(generation):
    path = f'/hls/{generation}/index.m3u8'
    code, headers, body = get(args.video_port, path)
    if code != 200 or header(headers, 'X-PiPlayer-Mode') != 'video':
        raise RuntimeError(f'Video manifest returned {code}')
    lines = body.decode().splitlines()
    if '#EXT-X-ENDLIST' in lines:
        raise RuntimeError('Manifest is not live')
    segments = [line for line in lines if line and not line.startswith('#')]
    if not segments:
        raise RuntimeError('Manifest has no segments')
    return path, segments


def send_jpeg(path):
    local = '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'
    batch = f'put {local} /data/still/image.part\nrename /data/still/image.part /data/still/image.jpg\n'
    result = subprocess.run(['sftp', '-b', '-', '-P', str(args.ssh_port), *common,
                             f'player@{args.host}'], input=batch, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'JPEG SFTP failed: {result.stderr.strip()}')


def wait_keepalive_change(conn, expected, timeout=12):
    deadline = time.monotonic() + timeout
    retired = False
    while time.monotonic() < deadline:
        try:
            conn.request('GET', '/')
            response = conn.getresponse()
            current = response.getheader('X-PiPlayer-Mode')
            response.read()
            if current == expected:
                return 'old connection' if not retired else 'new connection after old connection closed'
        except (OSError, http.client.HTTPException):
            conn.close()
            retired = True
            conn = http.client.HTTPConnection(args.host, args.still_port, timeout=4)
        time.sleep(0.5)
    raise RuntimeError('Keep-alive requests did not converge to the new mode')


if remote('hostname').stdout.strip() != 'piplayer':
    raise RuntimeError('Target hostname is not piplayer')
remote('test -x /usr/sbin/player-network')
addresses = remote('ip -o -4 address show').stdout
interfaces = {}
for line in addresses.splitlines():
    match = re.match(r'\d+:\s+(\S+).*?\binet\s+(10\.0\.[23]\.15)/', line)
    if match:
        interfaces[match.group(2)] = match.group(1).split('@')[0]
if set(interfaces) != {'10.0.2.15', '10.0.3.15'} or interfaces['10.0.2.15'] == interfaces['10.0.3.15']:
    raise RuntimeError('Expected both guest addresses on distinct interfaces')
iface = interfaces['10.0.2.15']
if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', iface) or iface.startswith('-'):
    raise RuntimeError('Unsafe discovered interface name')

original = remote('cat /etc/player/player.conf').stdout
remote(". /etc/player/player.conf; test \"${INTERFACE_MODES:-0}\" = 0")
remote('cp -p /etc/player/player.conf /run/player-interface-smoke.conf')
backup = '/data/still/.smoke-backup-' + uuid.uuid4().hex
backup_q = shlex.quote(backup)
remote(f'mkdir -p /data/still; if [ -e /data/still/image.jpg ]; then mv /data/still/image.jpg {backup_q}; fi')
aliases = False
try:
    previous_generation = status(args.video_port)[1].get('generation')
    subprocess.run(['python3', str(ROOT / 'scripts/upload.py'), str(video), '--host', args.host,
                    '--port', str(args.ssh_port), '--key', str(args.key)], check=True)
    first = wait_until(lambda: (s if (s := status(args.video_port)[1]).get('state') == 'playing'
                                and s.get('audio') is True and s.get('generation') != previous_generation
                                else None), 'uploaded video with audio')
    set_mode(1, iface)
    wait_mode(args.still_port, 'still')
    wait_mode(args.video_port, 'video')
    for port, expected in ((args.still_port, 'still'), (args.video_port, 'video')):
        actual, _ = status(port)
        if actual != expected:
            raise RuntimeError(f'Wrong status mode on {port}: {actual}')
    if not mode(args.still_port, 'still') or header(get(args.still_port, '/', {'Host': 'anything.invalid'})[1], 'X-PiPlayer-Mode') != 'still':
        raise RuntimeError('Host header changed still presentation')
    generation = first['generation']
    path, before = manifest(generation)
    duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                               '-of', 'default=noprint_wrappers=1:nokey=1', str(video)], text=True))
    if not math.isfinite(duration) or duration <= 0:
        raise RuntimeError('Demo must have a finite positive duration')
    time.sleep(duration + 1)
    _, after = manifest(generation)
    if not set(after) - set(before):
        raise RuntimeError('Video manifest did not advance during the source duration')
    def next_segment():
        _, current = manifest(generation)
        return next((name for name in current if name not in after), None)
    segment = wait_until(next_segment, 'new segment after source duration')
    segment_path = path.rsplit('/', 1)[0] + '/' + segment
    for resource in (path, segment_path):
        if get(args.still_port, resource)[0] != 404 or get(args.video_port, resource)[0] != 200:
            raise RuntimeError(f'Unexpected HLS accessibility for {resource}')
    wait_until(lambda: get(args.video_port, '/stream.m3u8')[0] == 200, 'fixed direct HLS URL')
    direct = get(args.video_port, '/stream.m3u8')
    if (get(args.still_port, '/stream.m3u8')[0] != 404
            or 'application/vnd.apple.mpegurl' not in (header(direct[1], 'Content-Type') or '')
            or b'/hls/' not in direct[2]):
        raise RuntimeError('Fixed HLS URL did not follow interface presentation mode')
    print('PASS: still/video destinations, Host override, HLS isolation and progress')

    fallback = get(args.still_port, '/still-image.jpg')
    if fallback[0] != 200 or 'svg' not in (header(fallback[1], 'Content-Type') or ''):
        raise RuntimeError('Missing JPEG did not serve SVG placeholder')
    with tempfile.TemporaryDirectory(prefix='piplayer-picture-smoke-') as directory:
        jpeg = Path(directory) / 'image.jpg'
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-frames:v', '1', str(jpeg)], check=True)
        send_jpeg(jpeg)
        code, headers, body = get(args.still_port, '/still-image.jpg')
        if code != 200 or not (header(headers, 'Content-Type') or '').startswith('image/jpeg') or body != jpeg.read_bytes():
            raise RuntimeError('Uploaded JPEG response did not match')
    print('PASS: placeholder and atomic JPEG SFTP upload')

    conn = http.client.HTTPConnection(args.host, args.still_port, timeout=4)
    conn.request('GET', '/')
    response = conn.getresponse()
    if response.getheader('X-PiPlayer-Mode') != 'still':
        raise RuntimeError('Expected still on initial persistent connection')
    response.read()
    set_mode(0, iface)
    convergence = wait_keepalive_change(conn, 'video')
    conn.close()
    wait_mode(args.still_port, 'video', 12)
    wait_mode(args.video_port, 'video', 12)
    print(f'PASS: disabled mode on both destinations; {convergence}')

    set_mode(1, iface)
    wait_mode(args.still_port, 'still')
    aliases = True
    remote(f'ip address add 10.0.2.99/24 dev {iface}; ip -6 address add fd50::99/64 dev {iface}')
    def aliases_present():
        lines = remote('cat /run/player-network/presentation.map').stdout.splitlines()
        return '10.0.2.99 still;' in lines and 'fd50::99 still;' in lines
    wait_until(aliases_present, 'IPv4 and IPv6 aliases in map')
    result = remote("wget -q -O - 'http://10.0.2.99:8080/'", check=False)
    if result.returncode or 'id="picture"' not in result.stdout:
        raise RuntimeError('IPv4 alias did not serve the still page')
    result = remote("wget -q -O - 'http://[fd50::99]:8080/'", check=False)
    if result.returncode:
        address_state = remote(f'ip -o -6 address show dev {iface}').stdout
        if not any('fd50::99/64' in line and 'tentative' not in line and 'dadfailed' not in line
                   for line in address_state.splitlines()):
            raise RuntimeError('IPv6 alias is not usable on the guest interface')
        if 'bad address' not in result.stderr.lower() and 'invalid url' not in result.stderr.lower():
            raise RuntimeError(f'IPv6 HTTP request failed: {result.stderr.strip()}')
        print(f'SKIP: guest wget cannot use the IPv6 URL; HTTP not verified: {result.stderr.strip()}')
    elif 'id="picture"' not in result.stdout:
        raise RuntimeError('IPv6 alias did not serve the still page')
    else:
        print('PASS: IPv6 alias HTTP still page')
    remote(f'ip address del 10.0.2.99/24 dev {iface}; ip -6 address del fd50::99/64 dev {iface}')
    aliases = False
    def aliases_removed():
        lines = remote('cat /run/player-network/presentation.map').stdout.splitlines()
        return '10.0.2.99 still;' not in lines and 'fd50::99 still;' not in lines
    wait_until(aliases_removed, 'alias removal from map')
    print('PASS: IPv4/IPv6 alias map updates and IPv4 HTTP still page')

    if args.reboot:
        remote('sync; reboot', check=False)
        time.sleep(5)
        wait_mode(args.still_port, 'still', 120)
        wait_mode(args.video_port, 'video', 120)
        wait_until(lambda: remote('true', check=False).returncode == 0, 'SSH after reboot', 90)
        print('PASS: still/video modes after reboot')
finally:
    if aliases:
        remote(f'ip address del 10.0.2.99/24 dev {iface} 2>/dev/null || true; ip -6 address del fd50::99/64 dev {iface} 2>/dev/null || true', check=False)
    remote('umask 077; cat > /etc/player/player.conf.smoke-restore && chmod 600 /etc/player/player.conf.smoke-restore && mv /etc/player/player.conf.smoke-restore /etc/player/player.conf', data=original)
    remote(f'rm -f /data/still/image.part /data/still/image.jpg; if [ -e {backup_q} ]; then mv {backup_q} /data/still/image.jpg; fi; rm -f /run/player-interface-smoke.conf')
    wait_mode(args.still_port, 'video', 45)
    wait_mode(args.video_port, 'video', 45)
    print('PASS: restored original configuration and video modes')
print('STILL SMOKE PASS')
