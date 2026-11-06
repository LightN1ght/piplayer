import base64
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / 'board/player/rootfs-overlay/usr/libexec/player-apply-setup'
KEY = base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20' + bytes(range(32))).decode()


class FirstBootSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        fake = self.path / 'chpasswd'
        fake.write_text('#!/bin/sh\ncat > "$CAPTURE"\n')
        fake.chmod(0o755)
        self.env = {**os.environ, 'PLAYER_SETUP_CONFIG': str(self.path / 'etc/player.conf'),
                    'PLAYER_SETUP_ROOT_KEY': str(self.path / 'root/authorized_keys'),
                    'PLAYER_SETUP_PLAYER_KEY': str(self.path / 'player/authorized_keys'),
                    'PLAYER_SETUP_CHPASSWD': str(fake), 'CAPTURE': str(self.path / 'capture')}
        self.valid = (f'SSID=My Camera\nWIFI_PASSWORD=TestPassword1\nCOUNTRY=RU\nCHANNEL=6\n'
                      f'SFTP_PASSWORD=OtherPassword2\nADMIN_KEY=ssh-ed25519 {KEY} comment\n')

    def run_setup(self, text):
        source = self.path / 'setup.txt'
        source.write_text(text)
        return subprocess.run([str(HELPER), str(source)], env=self.env, capture_output=True, text=True)

    def test_applies_individual_settings_and_key(self):
        result = self.run_setup(self.valid.replace('\n', '\r\n'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AP_SSID='My Camera'", (self.path / 'etc/player.conf').read_text())
        self.assertEqual((self.path / 'capture').read_text(), 'player:OtherPassword2\n')
        self.assertEqual((self.path / 'root/authorized_keys').read_text(), f'ssh-ed25519 {KEY}\n')
        self.assertEqual((self.path / 'player/authorized_keys').read_text(), f'ssh-ed25519 {KEY}\n')
        self.assertEqual((self.path / 'etc/player.conf').stat().st_mode & 0o777, 0o600)
        self.assertEqual(result.stdout + result.stderr, '')

    def test_rejects_invalid_and_shell_content_without_changing_existing_files(self):
        for invalid in (self.valid + 'SSID=duplicate\n',
                        self.valid.replace('My Camera', "name'$(touch /tmp/unsafe)"),
                        self.valid.replace('CHANNEL=6', 'CHANNEL=99'),
                        self.valid.replace(KEY, 'AAAAC3NzaC1lZDI1NTE5AAAAI' + 'A' * 41 + '=='),
                        self.valid.replace(KEY, 'badkey')):
            with self.subTest(invalid=invalid):
                result = self.run_setup(invalid)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((self.path / 'capture').exists())
                self.assertFalse((self.path / 'etc/player.conf').exists())
                self.assertEqual(result.stdout + result.stderr, '')


if __name__ == '__main__':
    unittest.main()
