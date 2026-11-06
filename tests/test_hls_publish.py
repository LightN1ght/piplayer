"""Tests for the stable HLS manifest; no network or target device needed."""
import json
import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / 'board/player/rootfs-overlay'
PUBLISHER = OVERLAY / 'usr/bin/player-publish'
AWK = OVERLAY / 'usr/libexec/player-publish.awk'


class StablePlaylist(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='piplayer-publish-')
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        self.now = 100
        self.env = dict(os.environ, PLAYER_RUNTIME=str(self.runtime), PLAYER_PUBLISH_AWK=str(AWK))
        self.public = self.runtime / 'stream.m3u8'

    def run_once(self, ok=True):
        result = subprocess.run(['sh', str(PUBLISHER), '--once'],
                                env=dict(self.env, PLAYER_PUBLISH_NOW=str(self.now)),
                                text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def private(self, generation, numbers, duration=2):
        folder = self.runtime / 'hls' / generation
        folder.mkdir(parents=True, exist_ok=True)
        lines = ['#EXTM3U', '#EXT-X-TARGETDURATION:6', f'#EXT-X-MEDIA-SEQUENCE:{numbers[0]}']
        for number in numbers:
            filename = f'segment-{number:09d}.ts'
            (folder / filename).write_bytes(b'test transport stream')
            lines += [f'#EXTINF:{duration},', filename]
        (folder / 'index.m3u8').write_text('\n'.join(lines) + '\n')
        (self.runtime / 'status.json').write_text(json.dumps({'state': 'playing', 'generation': generation}, separators=(',', ':')))

    def parse(self):
        lines = self.public.read_text().splitlines()
        sequence = int(next(line.split(':', 1)[1] for line in lines if line.startswith('#EXT-X-MEDIA-SEQUENCE:')))
        disc = int(next(line.split(':', 1)[1] for line in lines if line.startswith('#EXT-X-DISCONTINUITY-SEQUENCE:')))
        uris = [line for line in lines if line.startswith('/hls/')]
        return lines, sequence, disc, uris

    def test_no_input_and_initial_publish_with_dedup_after_restart(self):
        self.run_once()
        self.assertFalse(self.public.exists())
        self.private('gen-a', [0, 1])
        self.run_once()
        lines, sequence, disc, uris = self.parse()
        self.assertEqual(sequence, 0)
        self.assertEqual(disc, 0)
        self.assertIn('#EXT-X-TARGETDURATION:6', lines)
        self.assertEqual(uris, ['/hls/gen-a/segment-000000000.ts', '/hls/gen-a/segment-000000001.ts'])
        self.run_once()  # New shell process uses the saved state.
        self.assertEqual(self.parse()[3], uris)
        self.private('gen-a', [1, 2, 3])
        self.run_once()
        self.assertEqual(len(self.parse()[3]), 4)

    def test_replacement_and_gap_mark_discontinuity_with_contiguous_sequence(self):
        self.private('gen-a', [0, 1, 2])
        self.run_once()
        self.private('gen-b', [0, 1])
        self.run_once()
        lines, seq, disc, uris = self.parse()
        self.assertEqual((seq, disc, len(uris)), (0, 0, 5))
        self.assertEqual(lines[lines.index('/hls/gen-b/segment-000000000.ts') - 2], '#EXT-X-DISCONTINUITY')
        self.private('gen-b', [5, 6])
        self.run_once()
        lines, seq, disc, uris = self.parse()
        self.assertEqual((seq, len(uris)), (0, 7))
        self.assertEqual(lines.count('#EXT-X-DISCONTINUITY'), 2)

    def test_retention_and_discontinuity_sequence_after_prune(self):
        self.private('gen-a', [0, 1, 2, 3, 4])
        self.run_once()
        old_file = self.runtime / 'hls/gen-a/segment-000000000.ts'
        self.private('gen-b', [0, 1, 2, 3, 4])
        self.run_once()
        for start in (5, 10, 15):
            self.now += 1
            self.private('gen-b', list(range(start, start + 5)))
            self.run_once()
        lines, sequence, disc, uris = self.parse()
        self.assertGreater(sequence, 5)
        self.assertEqual(disc, 1)
        self.assertNotIn('#EXT-X-DISCONTINUITY', lines)
        self.assertTrue(old_file.exists())
        self.now = 136  # First old segment was retired at t=101.
        self.run_once()
        self.assertTrue(old_file.exists(), 'Old segment removed before 36 seconds after retirement')
        self.now += 1
        self.run_once()
        self.assertFalse(old_file.exists(), 'Expired retired segment was not removed')
        self.assertTrue(uris)

    def test_reject_long_segment_without_changing_last_good_playlist(self):
        self.private('gen-a', [0, 1])
        self.run_once()
        previous = self.public.read_bytes()
        self.private('gen-b', [0], duration=6.01)
        self.run_once(ok=False)
        self.assertEqual(self.public.read_bytes(), previous)
        self.assertTrue((self.runtime / 'stream-error.log').exists())

    def test_missing_segment_does_not_publish_broken_manifest(self):
        self.private('gen-a', [0])
        (self.runtime / 'hls/gen-a/segment-000000000.ts').unlink()
        self.run_once(ok=False)
        self.assertFalse(self.public.exists())

    def test_large_sequence_is_written_as_a_decimal_integer(self):
        (self.runtime / 'publish.state').write_text('M|1000001|gen-old|9|3\n')
        self.private('gen-new', [0])
        self.run_once()
        lines, sequence, _, _ = self.parse()
        self.assertEqual(sequence, 1000001)
        self.assertIn('#EXT-X-MEDIA-SEQUENCE:1000001', lines)

    def test_lock_skips_concurrent_once_without_touching_state(self):
        self.private('gen-a', [0])
        with (self.runtime / 'publish.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_once()
            self.assertFalse(self.public.exists())
            self.assertFalse((self.runtime / 'publish.state').exists())
        self.run_once()
        self.assertTrue(self.public.exists())

    def test_heartbeat_updates_without_input(self):
        process = subprocess.Popen(['sh', str(PUBLISHER)], env=self.env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        heartbeat = self.runtime / 'publisher-heartbeat'
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not heartbeat.exists():
                time.sleep(0.05)
            self.assertTrue(heartbeat.exists())
            first = int(heartbeat.read_text())
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and int(heartbeat.read_text()) <= first:
                time.sleep(0.1)
            self.assertGreater(int(heartbeat.read_text()), first)
            self.assertFalse(self.public.exists())
        finally:
            process.terminate()
            try:
                process.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()

    def test_gc_unregistered_current_segment_but_keeps_private_and_registered(self):
        self.private('gen-a', [0, 1])
        self.run_once()
        folder = self.runtime / 'hls/gen-a'
        orphan = folder / 'segment-000000100.ts'
        orphan.write_bytes(b'orphan')
        private_only = folder / 'private-only.ts'
        private_only.write_bytes(b'private')
        (folder / 'index.m3u8').write_text('#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:2,\nprivate-only.ts\n')
        recent_dir = self.runtime / 'hls/gen-new'
        recent_dir.mkdir()
        # A registered segment and an unregistered private URI must both stay.
        old = time.time() - 180
        for path in (orphan, private_only, folder / 'segment-000000000.ts'):
            os.utime(path, (old, old))
        self.run_once()
        self.assertFalse(orphan.exists())
        self.assertTrue((folder / 'segment-000000000.ts').exists())
        self.assertTrue(private_only.exists())
        self.assertTrue(recent_dir.exists(), 'A newly created generation directory was removed')


if __name__ == '__main__':
    unittest.main()
