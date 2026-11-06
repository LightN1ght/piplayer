"""Exercise the real worker and FFmpeg, including upload and stream recovery."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'board/player/rootfs-overlay/usr/bin/playerd'
PUBLISHER = ROOT / 'board/player/rootfs-overlay/usr/bin/player-publish'
PUBLISH_AWK = ROOT / 'board/player/rootfs-overlay/usr/libexec/player-publish.awk'


class MediaLifecycle(unittest.TestCase):
    def test_upload_loop_audio_replacement_and_recovery(self):
        with tempfile.TemporaryDirectory(prefix='piplayer-test-') as directory:
            base = Path(directory)
            data, runtime = base / 'data', base / 'run'
            incoming = data / 'incoming'
            incoming.mkdir(parents=True)
            sample = base / 'sample.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                            'testsrc2=size=320x180:rate=25', '-f', 'lavfi', '-i',
                            'sine=frequency=440:sample_rate=48000', '-t', '4',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                            '-g', '25', '-sc_threshold', '0', '-c:a', 'aac', str(sample)], check=True)
            env = dict(os.environ, PLAYER_DATA=str(data), PLAYER_RUNTIME=str(runtime), PLAYER_INTERVAL='0.2',
                       PLAYER_STALL_TIMEOUT='4', PLAYER_PUBLISHER=str(PUBLISHER), PLAYER_PUBLISH_AWK=str(PUBLISH_AWK))
            worker = subprocess.Popen(['sh', str(WORKER)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            def status():
                try:
                    return json.loads((runtime / 'status.json').read_text())
                except (FileNotFoundError, json.JSONDecodeError):
                    return {}

            def wait_for(predicate, timeout=15):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    self.assertIsNone(worker.poll(), 'Worker unexpectedly exited')
                    value = status()
                    if predicate(value):
                        return value
                    time.sleep(0.1)
                self.fail(f'Timed out. status={status()}, log={(runtime / "ffmpeg.log").read_text() if (runtime / "ffmpeg.log").exists() else ""}')

            try:
                wait_for(lambda s: s.get('state') == 'waiting')
                partial = incoming / 'first.part'
                shutil.copyfile(sample, partial)
                time.sleep(0.5)
                self.assertFalse((data / 'media/current.mp4').exists(), 'Partial upload was activated')
                partial.rename(incoming / 'first.ready.mp4')
                first = wait_for(lambda s: s.get('state') == 'playing')
                self.assertTrue(first['audio'])
                playlist = runtime / 'hls' / first['generation'] / 'index.m3u8'
                initial = playlist.read_text()
                initial_segments = {line for line in initial.splitlines() if line and not line.startswith('#')}
                self.assertTrue(initial_segments)
                # Exceed the four-second source duration: it must remain live.
                time.sleep(5)
                self.assertEqual(status()['state'], 'playing')
                self.assertEqual(status()['generation'], first['generation'])
                manifest = playlist.read_text()
                self.assertNotIn('#EXT-X-ENDLIST', manifest)
                segments = [line for line in manifest.splitlines() if line and not line.startswith('#')]
                new_segments = [name for name in segments if name not in initial_segments]
                self.assertTrue(new_segments, 'Playlist did not advance beyond the initial segments')
                time.sleep(3)
                self.assertEqual(status().get('generation'), first['generation'])
                self.assertEqual(status().get('state'), 'playing')
                later = [line for line in playlist.read_text().splitlines() if line and not line.startswith('#')]
                after_loop = [name for name in later if name not in segments]
                self.assertTrue(after_loop, 'Playlist stopped advancing after the source duration')
                segment = playlist.parent / after_loop[-1]
                self.assertGreater(segment.stat().st_size, 0)
                stream = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                                  'stream=codec_name', '-of', 'csv=p=0', str(segment)], text=True)
                self.assertIn('h264', stream)
                self.assertIn('aac', stream)
                (incoming / 'broken.ready.mp4').write_bytes(b'not an mp4')
                wait_for(lambda s: s.get('error') == 'unsupported_media')
                self.assertEqual(status()['generation'], first['generation'])
                self.assertTrue((incoming / 'broken.ready.mp4.rejected').exists())
                shutil.copyfile(sample, incoming / 'second.ready.mp4')
                second = wait_for(lambda s: s.get('state') == 'playing' and s.get('generation') != first['generation'])
                self.assertEqual(second['error'], '')
                # Kill the transcoder only; the worker must create a fresh stream.
                children = Path(f'/proc/{worker.pid}/task/{worker.pid}/children').read_text().split()
                for child in children:
                    try:
                        cmdline = Path(f'/proc/{child}/cmdline').read_bytes()
                        if b'ffmpeg' in cmdline:
                            os.kill(int(child), 9)
                    except ProcessLookupError:
                        pass
                recovered = wait_for(lambda s: s.get('state') == 'playing' and s.get('generation') != second['generation'])
                # A live but stopped FFmpeg must also be detected by the watchdog.
                children = Path(f'/proc/{worker.pid}/task/{worker.pid}/children').read_text().split()
                ffmpeg_pids = []
                for child in children:
                    try:
                        if b'ffmpeg' in Path(f'/proc/{child}/cmdline').read_bytes():
                            ffmpeg_pids.append(int(child))
                    except ProcessLookupError:
                        pass
                self.assertEqual(len(ffmpeg_pids), 1, 'Expected exactly one running FFmpeg')
                os.kill(ffmpeg_pids[0], signal.SIGSTOP)
                wait_for(lambda s: s.get('state') == 'playing' and s.get('generation') != recovered['generation'], timeout=20)
                # Public HLS deliberately retains referenced/retired segments
                # across generations; it is no longer just one private window.
                self.assertLessEqual(len(list((runtime / 'hls').glob('*/*.ts'))), 40)
            finally:
                worker.terminate()
                try:
                    worker.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
                    worker.communicate()


if __name__ == '__main__':
    unittest.main()

