#!/usr/bin/env python3
"""Test an already booted appliance. Replaces its active video with the test clip."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--ssh-port', type=int, default=2222)
parser.add_argument('--http-port', type=int, default=8080)
parser.add_argument('--video', type=Path, default=ROOT / '.build/demo.mp4')
parser.add_argument('--key', type=Path, default=ROOT / '.local/admin_ed25519')
parser.add_argument('--reboot', action='store_true', help='Also reboot this test appliance')
args = parser.parse_args()
if args.host.startswith('-') or any(c in args.host for c in '\r\n @'):
    parser.error('Invalid host')
known = str(ROOT / '.local/known_hosts').replace('\\', '\\\\').replace('"', '\\"')
ssh = ['ssh', '-p', str(args.ssh_port), '-i', str(args.key), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=accept-new',
       '-o', f'UserKnownHostsFile="{known}"', f'root@{args.host}']
base_url = f'http://{args.host}:{args.http_port}'


def remote(command, check=True):
    result = subprocess.run(ssh + [command], text=True, capture_output=True)
    if result.returncode:
        print(f'SSH command failed ({result.returncode}): {command}\n{result.stderr}', flush=True)
        if check:
            raise subprocess.CalledProcessError(result.returncode, result.args, result.stdout, result.stderr)
    return result


def wait_for_ssh(timeout=90):
    deadline = time.monotonic() + timeout
    last_error = 'connection timed out'
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(ssh + ['true'], text=True, capture_output=True,
                                    timeout=max(0.1, min(8, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            last_error = 'SSH connection timed out'
        else:
            if result.returncode == 0:
                return
            last_error = result.stderr.strip() or f'exit status {result.returncode}'
            message = last_error.lower()
            permanent = ('permission denied', 'host key verification failed',
                         'remote host identification has changed', 'no such identity',
                         'unprotected private key file')
            transient = ('connection refused', 'connection reset', 'connection timed out',
                         'connection closed', 'operation timed out', 'no route to host')
            if (result.returncode != 255 or any(item in message for item in permanent)
                    or not any(item in message for item in transient)):
                raise RuntimeError(f'SSH readiness failed: {last_error}')
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError(f'SSH readiness timed out after {timeout}s: {last_error}')


def status():
    try:
        with urllib.request.urlopen(base_url + '/status.json', timeout=3) as response:
            return json.load(response)
    except (OSError, ValueError):
        return {}


def wait_for(predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = status()
        if predicate(value):
            return value
        time.sleep(1)
    raise RuntimeError(f'Timeout, last status: {status()}')


def upload(video):
    subprocess.run(['python3', str(ROOT / 'scripts/upload.py'), str(video),
                    '--host', args.host, '--port', str(args.ssh_port), '--key', str(args.key)], check=True)


def playlist(generation):
    url = base_url + '/hls/' + generation + '/index.m3u8'
    with urllib.request.urlopen(url, timeout=5) as response:
        if response.headers.get_content_type() != 'application/vnd.apple.mpegurl':
            raise RuntimeError('Unexpected HLS playlist content type')
        manifest = response.read().decode()
    if '#EXT-X-ENDLIST' in manifest:
        raise RuntimeError('Playlist is not live')
    lines = manifest.splitlines()
    segments = [line for line in lines if line and not line.startswith('#')]
    if not segments or not any(line.startswith('#EXT-X-MEDIA-SEQUENCE:') for line in lines):
        raise RuntimeError('Playlist has no media sequence or segments')
    return url, segments


def check_progress(generation, minimum_elapsed=0, timeout=90):
    url, initial = playlist(generation)
    started = time.monotonic()
    deadline = started + max(timeout, minimum_elapsed + 30)
    baseline = None
    while time.monotonic() < deadline:
        time.sleep(1)
        current = status()
        if current.get('generation') != generation or current.get('state') != 'playing':
            raise RuntimeError(f'Stream changed or stopped during progress check: {current}')
        _, segments = playlist(generation)
        if time.monotonic() - started < minimum_elapsed:
            continue
        if baseline is None:
            if minimum_elapsed and not any(segment not in initial for segment in segments):
                raise RuntimeError('HLS playlist did not progress during the source duration')
            baseline = segments
            continue
        new = [segment for segment in segments if segment not in baseline]
        if new:
            with urllib.request.urlopen(url.rsplit('/', 1)[0] + '/' + new[-1], timeout=5) as response:
                if not response.read():
                    raise RuntimeError('New HLS segment is empty')
            return url, new[-1]
    raise RuntimeError(f'HLS playlist did not progress after {minimum_elapsed:.1f}s')


wait_for(lambda s: bool(s))
wait_for_ssh()
remote('command -v stat >/dev/null && stat -c "%i:%s:%Y" /data >/dev/null && /usr/sbin/nginx -t && /usr/sbin/sshd -t && id player')
print('PASS: HTTP, administrative SSH, nginx and sshd configuration')
previous_generation = status().get('generation')
upload(args.video)
first = wait_for(lambda s: s.get('state') == 'playing' and s.get('audio') is True and s.get('generation') != previous_generation)
duration = float(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                          '-of', 'default=noprint_wrappers=1:nokey=1', str(args.video)], text=True))
if not math.isfinite(duration) or duration <= 0:
    raise RuntimeError('Test video must have a finite, positive duration')
manifest_url, segment = check_progress(first['generation'], minimum_elapsed=duration + 1)
with tempfile.TemporaryDirectory(prefix='piplayer-smoke-') as directory:
    path = Path(directory) / 'segment.ts'
    with urllib.request.urlopen(manifest_url.rsplit('/', 1)[0] + '/' + segment) as response:
        path.write_bytes(response.read())
    codecs = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                      'stream=codec_name', '-of', 'csv=p=0', str(path)], text=True)
    assert 'h264' in codecs and 'aac' in codecs
    # Decode the downloaded audio, not only inspect its metadata.
    pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0',
                                   '-f', 's16le', '-acodec', 'pcm_s16le', '-'])
    assert pcm and any(pcm), 'Audio is empty or silent'
    broken = Path(directory) / 'invalid.mp4'
    broken.write_bytes(b'not a media file')
    upload(broken)
    after_bad = wait_for(lambda s: s.get('error') == 'unsupported_media')
    assert after_bad['state'] == 'playing' and after_bad['generation'] == first['generation']
print('PASS: SFTP upload, HLS progress beyond source duration, decoded non-silent AAC, invalid-file rejection')

remote('kill $(pidof ffmpeg)')
recovered = wait_for(lambda s: s.get('state') == 'playing' and s.get('generation') != first['generation'])
assert recovered['error'] == ''
check_progress(recovered['generation'])
print('PASS: recovery after FFmpeg termination')

if args.reboot:
    remote('sync; reboot', check=False)
    time.sleep(4)
    restarted = wait_for(lambda s: s.get('state') == 'playing' and s.get('generation') != recovered['generation'], timeout=120)
    assert restarted['audio'] is True
    remote('test -s /data/media/current.mp4')
    check_progress(restarted['generation'])
    print('PASS: reboot, persistent video, automatic stream restart, unchanged SSH host key')
print(remote('df -k /data; uname -r').stdout.strip())
print('SMOKE PASS')
