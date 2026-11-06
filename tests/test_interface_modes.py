"""Isolated contract tests for the destination-address presentation map."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DAEMON = ROOT / 'board/player/rootfs-overlay/usr/sbin/player-network'


class InterfaceModes(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='piplayer-network-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = self.base / 'player.conf'
        self.runtime = self.base / 'runtime'
        self.mapfile = self.runtime / 'presentation.map'
        self.pidfile = self.base / 'nginx.pid'
        self.state = self.base / 'addresses.json'
        self.calls = self.base / 'nginx-calls.jsonl'
        self.fail = self.base / 'nginx-fail'
        self.state.write_text('{}')
        self.calls.write_text('')
        self.pidfile.write_text(str(os.getpid()))
        self.ip = self.base / 'ip'
        self.ip.write_text('''#!/usr/bin/env python3
import json, os, sys
addresses = json.load(open(os.environ['TEST_ADDRESS_STATE']))
if len(sys.argv) != 6 or sys.argv[1:5] != ['-o', 'address', 'show', 'dev']:
    sys.exit(2)
interface = sys.argv[5]
if interface not in addresses:
    sys.exit(1)
for line in addresses[interface]:
    print(line)
''')
        self.nginx = self.base / 'nginx'
        self.nginx.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
with open(os.environ['TEST_NGINX_CALLS'], 'a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\\n')
failure = pathlib.Path(os.environ['TEST_NGINX_FAIL'])
mode = failure.read_text().strip() if failure.exists() else ''
if mode == 'test' and '-t' in sys.argv:
    sys.exit(1)
if mode == 'reload' and '-s' in sys.argv and 'reload' in sys.argv:
    sys.exit(1)
''')
        self.ip.chmod(0o755)
        self.nginx.chmod(0o755)
        self.env = dict(os.environ, PLAYER_NETWORK_CONFIG=str(self.config),
                        PLAYER_NETWORK_RUNTIME=str(self.runtime), PLAYER_NETWORK_IP=str(self.ip),
                        PLAYER_NETWORK_NGINX=str(self.nginx), PLAYER_NETWORK_NGINX_PID=str(self.pidfile),
                        PLAYER_NETWORK_INTERVAL='1', TEST_ADDRESS_STATE=str(self.state),
                        TEST_NGINX_CALLS=str(self.calls), TEST_NGINX_FAIL=str(self.fail))

    def addresses(self, values):
        self.state.write_text(json.dumps(values))

    def configure(self, mode='1', interfaces='eth0'):
        self.config.write_text(f"INTERFACE_MODES={mode}\nSTILL_INTERFACES='{interfaces}'\n")

    def run_daemon(self, option, check=True):
        result = subprocess.run(['sh', str(DAEMON), option], env=self.env, text=True, capture_output=True)
        if check:
            self.assertEqual(result.returncode, 0, f'{option}: {result.stderr}')
        return result

    def reloads(self):
        return [args for args in map(json.loads, self.calls.read_text().splitlines())
                if '-s' in args and 'reload' in args]

    def test_disabled_and_missing_config_render_empty(self):
        self.addresses({'eth0': ['2: eth0    inet 192.0.2.10/24 scope global eth0']})
        self.assertEqual(self.run_daemon('--render').stdout.strip(), '')
        self.configure('0')
        self.assertEqual(self.run_daemon('--render').stdout.strip(), '')

    def test_render_addresses_are_unique_sorted_and_filter_unready_ipv6(self):
        self.configure(interfaces='eth0 eth1 absent0')
        self.addresses({
            'eth0': ['2: eth0    inet 192.0.2.10/24 scope global eth0',
                     '2: eth0    inet 192.0.2.11/24 scope global secondary eth0',
                     '2: eth0    inet6 2001:db8::10/64 scope global',
                     '2: eth0    inet6 2001:db8::11/64 scope global tentative',
                     '2: eth0    inet6 2001:db8::12/64 scope global dadfailed'],
            'eth1': ['3: eth1    inet 192.0.2.10/24 scope global eth1',
                     '3: eth1    inet6 fe80::1234/64 scope link'],
            'eth2': ['4: eth2    inet 198.51.100.2/24 scope global eth2'],
        })
        self.assertEqual(self.run_daemon('--render').stdout.splitlines(),
                         ['192.0.2.10 still;', '192.0.2.11 still;',
                          '2001:db8::10 still;', 'fe80::1234 still;'])

    def test_once_updates_on_address_changes_and_skips_unchanged_reload(self):
        self.configure()
        self.addresses({'eth0': ['2: eth0    inet 192.0.2.10/24 scope global eth0']})
        self.run_daemon('--once')
        self.assertEqual(self.mapfile.read_text().strip(), '192.0.2.10 still;')
        initial_reloads = len(self.reloads())
        self.assertEqual(initial_reloads, 1)
        self.run_daemon('--once')
        self.assertEqual(len(self.reloads()), initial_reloads)
        self.addresses({'eth0': ['2: eth0    inet 192.0.2.20/24 scope global eth0']})
        self.run_daemon('--once')
        self.assertEqual(self.mapfile.read_text().strip(), '192.0.2.20 still;')
        self.assertEqual(len(self.reloads()), initial_reloads + 1)
        self.addresses({})
        self.run_daemon('--once')
        self.assertEqual(self.mapfile.read_text().strip(), '')
        self.assertEqual(len(self.reloads()), initial_reloads + 2)

    def test_no_running_nginx_does_not_reload(self):
        self.configure()
        self.pidfile.unlink()
        self.run_daemon('--once')
        self.assertEqual(self.reloads(), [])

    def test_bad_config_never_replaces_existing_map_or_logs_value(self):
        self.configure()
        self.addresses({'eth0': ['2: eth0    inet 192.0.2.10/24 scope global eth0']})
        self.run_daemon('--once')
        previous = self.mapfile.read_bytes()
        for mode, interfaces in [('badsecretvalue', 'eth0'), ('1', '../bad'),
                                 ('1', 'a' * 16)]:
            with self.subTest(mode=mode, interfaces=interfaces):
                self.configure(mode, interfaces)
                result = self.run_daemon('--once', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.mapfile.read_bytes(), previous)
                self.assertNotIn('badsecretvalue', result.stdout + result.stderr)
                for logfile in self.runtime.glob('*.log'):
                    self.assertNotIn('badsecretvalue', logfile.read_text())

    def test_nginx_test_and_reload_failures_roll_back(self):
        self.configure()
        self.addresses({'eth0': ['2: eth0    inet 192.0.2.10/24 scope global eth0']})
        self.run_daemon('--once')
        previous = self.mapfile.read_bytes()
        self.addresses({'eth0': ['2: eth0    inet 192.0.2.20/24 scope global eth0']})
        for failure in ('test', 'reload'):
            with self.subTest(failure=failure):
                self.fail.write_text(failure)
                result = self.run_daemon('--once', check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.mapfile.read_bytes(), previous)
                self.fail.unlink()


if __name__ == '__main__':
    unittest.main()
