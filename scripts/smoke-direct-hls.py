#!/usr/bin/env python3
"""Test the stable HLS URL on a test appliance; replaces its active video."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host', default='127.0.0.1')
parser.add_argument('--ssh-port', type=int, default=2225)
parser.add_argument('--http-port', type=int, default=8083)
parser.add_argument('--key', type=Path, default=ROOT / '.local/admin_ed25519')
args = parser.parse_args()
if args.host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9.-]+', args.host):
    parser.error('Host must be an IPv4 address or hostname')
if not all(1 <= port <= 65535 for port in (args.ssh_port, args.http_port)):
    parser.error('Ports must be in 1..65535')
known = str(ROOT / '.local/known_hosts').replace('\\', '\\\\').replace('"', '\\"')
ssh = ['ssh', '-p', str(args.ssh_port), '-i', str(args.key), '-o', 'BatchMode=yes',
       '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=accept-new',
       '-o', f'UserKnownHostsFile="{known}"', f'root@{args.host}']
base_url = f'http://{args.host}:{args.http_port}'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def remote(command):
    result = subprocess.run(ssh + [command], text=True, capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError(f'SSH check failed ({result.returncode}): {result.stderr.strip()}')
    return result.stdout.strip()


def get(path):
    with opener.open(base_url + path, timeout=5) as response:
        return response.headers, response.read()


def status():
    headers, body = get('/status.json')
    if headers.get('X-PiPlayer-Mode') != 'video':
        raise RuntimeError('Target HTTP address is not in video mode')
    return json.loads(body)


def playlist():
    headers, body = get('/stream.m3u8')
    if headers.get('X-PiPlayer-Mode') != 'video':
        raise RuntimeError('Direct HLS address is not in video mode')
    if headers.get_content_type() != 'application/vnd.apple.mpegurl':
        raise RuntimeError('Wrong direct HLS MIME type')
    if 'no-store' not in headers.get('Cache-Control', '').lower():
        raise RuntimeError('Direct HLS response does not disable caching')
    lines = body.decode('utf-8').splitlines()
    if '#EXTM3U' not in lines or '#EXT-X-TARGETDURATION:6' not in lines or '#EXT-X-ENDLIST' in lines:
        raise RuntimeError('Direct HLS is not the expected live playlist')
    seqs = [line for line in lines if line.startswith('#EXT-X-MEDIA-SEQUENCE:')]
    uris = [line for line in lines if line and not line.startswith('#')]
    if len(seqs) != 1 or not uris or not all(re.fullmatch(r'/hls/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+\.ts', uri) for uri in uris):
        raise RuntimeError('Direct HLS has invalid sequence or segment URIs')
    return lines, int(seqs[0].split(':', 1)[1]), uris


def upload(path):
    subprocess.run(['python3', str(ROOT / 'scripts/upload.py'), str(path), '--host', args.host,
                    '--port', str(args.ssh_port), '--key', str(args.key)], check=True, timeout=90)


def wait_for(predicate, description, consumer=None, error_log=None, timeout=90):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if consumer is not None and consumer.poll() is not None:
            details = error_log.read_text(errors='replace')[-4000:] if error_log.exists() else ''
            raise RuntimeError(f'HLS consumer exited ({consumer.returncode}): {details}')
        try:
            value = predicate()
            if value:
                return value
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    details = error_log.read_text(errors='replace')[-4000:] if error_log is not None and error_log.exists() else ''
    raise RuntimeError(f'Timeout waiting for {description}: {last_error or "condition not reached"}\n{details}')


if remote('hostname') != 'piplayer':
    raise RuntimeError('Target hostname is not piplayer')
remote('test -x /usr/bin/player-publish')
initial = status()

with tempfile.TemporaryDirectory(prefix='piplayer-direct-smoke-') as directory:
    base = Path(directory)
    clips, hashes = [], []
    for color, frequency in (('red', 440), ('blue', 880)):
        clip = base / f'{color}.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        f'color=c={color}:size=320x180:rate=25', '-f', 'lavfi', '-i',
                        f'sine=frequency={frequency}:sample_rate=48000', '-t', '4',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                        '-g', '25', '-sc_threshold', '0', '-c:a', 'aac', str(clip)], check=True, timeout=60)
        result = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(clip), '-map', '0:v:0',
                                          '-frames:v', '1', '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-'],
                                         text=True, timeout=30)
        hashes.append(next(line.rsplit(',', 1)[1].strip() for line in result.splitlines()
                           if line and not line.startswith('#')))
        clips.append(clip)
    if hashes[0] == hashes[1]:
        raise RuntimeError('Synthetic red and blue frames have the same hash')

    consumer = None
    reader = None
    decoded = []
    audio = base / 'audio.pcm'
    error_log = base / 'consumer.log'
    try:
        upload(clips[0])
        def red_ready():
            current = status()
            if current.get('state') != 'playing' or current.get('audio') is not True or current.get('generation') == initial.get('generation'):
                return None
            lines, sequence, uris = playlist()
            if not any(uri.startswith('/hls/' + current['generation'] + '/') for uri in uris):
                return None
            return current, (lines, sequence, uris)
        red_status, (_, initial_seq, initial_uris) = wait_for(red_ready, 'red direct HLS')
        old_uri = next(uri for uri in initial_uris if uri.startswith('/hls/' + red_status['generation'] + '/'))
        with error_log.open('w') as errors:
            consumer = subprocess.Popen(['ffmpeg', '-v', 'warning', '-nostdin', '-i', base_url + '/stream.m3u8',
                '-map', '0:v:0', '-an', '-vf', 'scale=320:180', '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-flush_packets', '1', 'pipe:1',
                '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', '-f', 's16le', str(audio)],
                stdout=subprocess.PIPE, stderr=errors, text=True)
        def collect():
            for line in consumer.stdout:
                if line and not line.startswith('#') and ',' in line:
                    decoded.append(line.rsplit(',', 1)[1].strip())
        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        pid = consumer.pid
        wait_for(lambda: hashes[0] in decoded, 'red decoded frames', consumer, error_log)
        upload(clips[1])
        wait_for(lambda: hashes[1] in decoded, 'blue decoded frames from same client', consumer, error_log)
        if consumer.pid != pid or consumer.poll() is not None:
            raise RuntimeError('The original HLS consumer did not remain running')
        new_status = status()
        if new_status.get('generation') == red_status.get('generation'):
            raise RuntimeError('Blue upload did not change generation')
        lines, new_seq, uris = playlist()
        if new_seq < initial_seq or '#EXT-X-DISCONTINUITY' not in lines or not any(
                uri.startswith('/hls/' + new_status['generation'] + '/') for uri in uris):
            raise RuntimeError('Playlist did not preserve sequence/discontinuity across replacement')
        if not get(old_uri)[1]:
            raise RuntimeError('Previously advertised segment is empty')
        def audible_audio():
            return audio.exists() and audio.stat().st_size > 0 and any(audio.read_bytes())
        wait_for(audible_audio, 'non-silent decoded AAC', consumer, error_log)
    finally:
        if consumer is not None:
            consumer.terminate()
            try:
                consumer.wait(timeout=5)
            except subprocess.TimeoutExpired:
                consumer.kill()
                consumer.wait(timeout=5)
            if reader is not None:
                reader.join(timeout=3)
            consumer.stdout.close()
    print('DIRECT HLS SMOKE PASS: one FFmpeg client decoded red then blue and non-silent AAC; old segment retained')
