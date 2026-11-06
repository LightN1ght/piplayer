"""Decode the fixed HLS URL in one real client while its source is replaced."""
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / 'board/player/rootfs-overlay'


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class DirectHls(unittest.TestCase):
    def test_one_client_decodes_new_video_and_audio_after_replacement(self):
        with tempfile.TemporaryDirectory(prefix='piplayer-direct-hls-') as directory:
            base = Path(directory)
            data, runtime = base / 'data', base / 'runtime'
            incoming = data / 'incoming'
            incoming.mkdir(parents=True)
            runtime.mkdir()
            clips = []
            expected = []
            for color, frequency in (('red', 440), ('blue', 880)):
                clip = base / (color + '.mp4')
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                                f'color=c={color}:size=320x180:rate=25', '-f', 'lavfi', '-i',
                                f'sine=frequency={frequency}:sample_rate=48000', '-t', '4',
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                                '-g', '25', '-sc_threshold', '0', '-c:a', 'aac', str(clip)], check=True)
                hashes = subprocess.check_output(['ffmpeg', '-v', 'error', '-i', str(clip),
                                                  '-map', '0:v:0', '-frames:v', '1', '-pix_fmt', 'yuv420p',
                                                  '-f', 'framemd5', '-'], text=True)
                expected.append(next(line.rsplit(',', 1)[1].strip() for line in hashes.splitlines()
                                     if line and not line.startswith('#')))
                clips.append(clip)
            self.assertNotEqual(expected[0], expected[1])
            env = dict(os.environ, PLAYER_DATA=str(data), PLAYER_RUNTIME=str(runtime), PLAYER_INTERVAL='0.2',
                       PLAYER_STALL_TIMEOUT='4',
                       PLAYER_PUBLISHER=str(OVERLAY / 'usr/bin/player-publish'),
                       PLAYER_PUBLISH_AWK=str(OVERLAY / 'usr/libexec/player-publish.awk'))
            server = http.server.ThreadingHTTPServer(('127.0.0.1', 0),
                        functools.partial(QuietHandler, directory=str(runtime)))
            worker = subprocess.Popen(['sh', str(OVERLAY / 'usr/bin/playerd')], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                      start_new_session=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}'
            consumer = None
            decoded = []
            consumer_error = base / 'consumer.log'
            audio = base / 'audio.pcm'

            def wait_for(predicate, timeout=35):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    self.assertIsNone(worker.poll(), 'Media worker stopped')
                    if consumer is not None:
                        self.assertIsNone(consumer.poll(), consumer_error.read_text())
                    if predicate():
                        return
                    time.sleep(0.1)
                logs = '\n'.join(p.read_text(errors='replace') for p in runtime.glob('*.log'))
                self.fail(f'Timed out; decoded={decoded[-5:]}\n{logs}\n{consumer_error.read_text() if consumer_error.exists() else ""}')

            def upload(clip, name):
                part = incoming / (name + '.part')
                shutil.copyfile(clip, part)
                part.rename(incoming / (name + '.ready.mp4'))

            try:
                upload(clips[0], 'red')
                public = runtime / 'stream.m3u8'
                wait_for(lambda: public.exists())
                first_manifest = public.read_text()
                original_uri = next(line for line in first_manifest.splitlines() if line.startswith('/hls/'))
                with consumer_error.open('w') as error_stream:
                    consumer = subprocess.Popen(['ffmpeg', '-v', 'warning', '-nostdin', '-i', url + '/stream.m3u8',
                        '-map', '0:v:0', '-an', '-pix_fmt', 'yuv420p', '-f', 'framemd5', '-flush_packets', '1', 'pipe:1',
                        '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', '-f', 's16le', str(audio)],
                        stdout=subprocess.PIPE, stderr=error_stream, text=True)

                def collect():
                    for line in consumer.stdout:
                        if line and not line.startswith('#') and ',' in line:
                            decoded.append(line.rsplit(',', 1)[1].strip())

                reader = threading.Thread(target=collect, daemon=True)
                reader.start()
                wait_for(lambda: expected[0] in decoded)
                first_generation = json.loads((runtime / 'status.json').read_text())['generation']
                consumer_pid = consumer.pid
                upload(clips[1], 'blue')
                wait_for(lambda: expected[1] in decoded)
                self.assertEqual(consumer.pid, consumer_pid, 'Client was restarted instead of following HLS')
                self.assertIsNone(consumer.poll())
                self.assertNotEqual(json.loads((runtime / 'status.json').read_text())['generation'], first_generation)
                with urllib.request.urlopen(url + original_uri, timeout=3) as response:
                    self.assertTrue(response.read(), 'Segment referenced before replacement vanished too soon')
                self.assertIn('#EXT-X-DISCONTINUITY', public.read_text())
                wait_for(lambda: audio.exists() and audio.stat().st_size > 0)
                self.assertTrue(any(audio.read_bytes()), 'Decoded AAC was silent')
                self.assertGreater(len(decoded), 25)
                # A valid H.264/AAC file can still have keyframes too far
                # apart for this bounded live profile. Keep the playing file.
                long_gop = base / 'long-gop.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                                'color=c=green:size=320x180:rate=25', '-f', 'lavfi', '-i',
                                'sine=frequency=660:sample_rate=48000', '-t', '8',
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                                '-g', '200', '-keyint_min', '200', '-sc_threshold', '0',
                                '-c:a', 'aac', str(long_gop)], check=True)
                current_generation = json.loads((runtime / 'status.json').read_text())['generation']
                blue_frames = decoded.count(expected[1])
                upload(long_gop, 'long-gop')
                wait_for(lambda: (incoming / 'long-gop.ready.mp4.rejected').exists())
                rejected = json.loads((runtime / 'status.json').read_text())
                self.assertEqual(rejected['error'], 'needs_preparation')
                self.assertEqual(rejected['state'], 'playing')
                self.assertEqual(rejected['generation'], current_generation)
                children_file = Path(f'/proc/{worker.pid}/task/{worker.pid}/children')

                def publisher_pids():
                    pids = []
                    for child in children_file.read_text().split():
                        try:
                            if b'player-publish' in Path(f'/proc/{child}/cmdline').read_bytes():
                                pids.append(int(child))
                        except FileNotFoundError:
                            pass
                    return pids

                publishers = publisher_pids()
                self.assertEqual(len(publishers), 1)
                old_publisher = publishers[0]
                blue_frames = decoded.count(expected[1])
                os.kill(old_publisher, signal.SIGSTOP)
                wait_for(lambda: (p := publisher_pids()) and old_publisher not in p, timeout=15)
                wait_for(lambda: decoded.count(expected[1]) > blue_frames)
                self.assertEqual(consumer.pid, consumer_pid)
                self.assertIsNone(consumer.poll())
                wait_for(lambda: decoded.count(expected[1]) > blue_frames)
                high_rate = base / 'high-rate.mp4'
                subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                                'color=c=green:size=320x180:rate=25', '-f', 'lavfi', '-i',
                                'sine=frequency=660:sample_rate=48000', '-t', '4',
                                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                                '-g', '25', '-sc_threshold', '0', '-b:v', '20000k', '-minrate', '20000k',
                                '-maxrate', '20000k', '-bufsize', '40000k', '-x264-params', 'nal-hrd=cbr',
                                '-c:a', 'aac', str(high_rate)], check=True)
                self.assertGreater(high_rate.stat().st_size, 4000000)
                upload(high_rate, 'high-rate')
                wait_for(lambda: (incoming / 'high-rate.ready.mp4.rejected').exists())
                rejected = json.loads((runtime / 'status.json').read_text())
                self.assertEqual(rejected['error'], 'needs_preparation')
                self.assertEqual(rejected['state'], 'playing')
                self.assertEqual(rejected['generation'], current_generation)
            finally:
                if consumer is not None:
                    consumer.terminate()
                    try:
                        consumer.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        consumer.kill()
                        consumer.wait()
                    consumer.stdout.close()
                worker.terminate()
                try:
                    worker.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.communicate()
                try:
                    os.killpg(worker.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
