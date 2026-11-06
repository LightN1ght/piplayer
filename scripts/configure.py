#!/usr/bin/env python3
"""Create per-project secrets once. Never print their contents."""
import json
import ipaddress
import os
from pathlib import Path
import secrets
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local'
LOCAL.mkdir(mode=0o700, exist_ok=True)
os.chmod(LOCAL, 0o700)
credentials = LOCAL / 'credentials.json'
if credentials.exists():
    data = json.loads(credentials.read_text())
else:
    data = {'ssid': 'PiPlayer', 'wifi_password': secrets.token_hex(8),
            'user': 'player', 'ssh_password': secrets.token_urlsafe(15),
            'country': 'RU', 'channel': 6, 'address': '192.168.50.1'}
    credentials.write_text(json.dumps(data, indent=2) + '\n')
    os.chmod(credentials, 0o600)
if not 1 <= len(data['ssid'].encode()) <= 32 or any(c in data['ssid'] for c in '\r\n'):
    raise SystemExit('SSID must be 1-32 bytes and contain no newlines')
if not 8 <= len(data['wifi_password']) <= 63 or not all(32 <= ord(c) <= 126 for c in data['wifi_password']):
    raise SystemExit('Wi-Fi password must be 8-63 printable ASCII characters')
if not 1 <= int(data['channel']) <= 11:
    raise SystemExit('Use a 2.4 GHz channel from 1 to 11')
if len(data['country']) != 2 or not data['country'].isalpha():
    raise SystemExit('Country must be a two-letter code')
if int(ipaddress.IPv4Address(data['address'])) % 256 != 1:
    raise SystemExit('AP address must end in .1 (DHCP uses .20-.100 in the same /24)')
password_hash = subprocess.check_output(
    ['openssl', 'passwd', '-6', '-stdin'], input=data['ssh_password']+'\n', text=True).strip()
(LOCAL / 'users.txt').write_text(
    f"player 1000 player 1000 {password_hash} /data /bin/sh - PiPlayer\n")
os.chmod(LOCAL / 'users.txt', 0o600)
values = {'AP_SSID': data['ssid'], 'AP_PASSWORD': data['wifi_password'],
          'AP_COUNTRY': data['country'], 'AP_CHANNEL': str(data['channel']),
          'AP_ADDRESS': data['address'], 'AP_INTERFACE': 'wlan0'}
(LOCAL / 'player.conf').write_text(''.join(f'{k}={shlex.quote(v)}\n' for k,v in values.items()))
os.chmod(LOCAL / 'player.conf', 0o600)
key = LOCAL / 'admin_ed25519'
if not key.exists():
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'piplayer-admin', '-f', str(key)], check=True)
print('Configuration ready in .local/ (credentials are not printed).')

