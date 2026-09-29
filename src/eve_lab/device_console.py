"""Cisco IOS XE console initialization and backup over the EVE host's SSH."""
import argparse
from ipaddress import IPv4Address
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit

import paramiko

from .config import load_server


_PROMPT = r'^[ \t]*[\w.()/:-]+[>#](?=[ \t]*(?:$|[*%]))'
_PRIVILEGED_PROMPT = r'^[ \t]*[\w.()/:-]+#(?=[ \t]*(?:$|[*%]))'
_OSC_TITLE = re.compile(r'\x1b\][012];[\x20-\x7e]*(?:\x07|\x1b\\)')


_READ_ONLY_UNSAFE = re.compile(
    r'(?im)(?:'
    r'Enter enable secret\s*:|Confirm enable secret\s*:|'
    r'Enter your selection\s*\[[^\]]+\]\s*:|'
    r'Username:\s*$|Password:\s*$|'
    r'Would you like to enter[^\n]*[?:]\s*$|'
    r'Press RETURN to get started[^\n]*$|'
    r'(?:confirm(?:ation)?|are you sure)[^\n]*(?:\[[^\]]+\]|[?:])\s*$|'
    r'^[ \t]*[\w.()/:-]+\(config[^)]*\)#[ \t]*(?:$|[*%])'
    r')'
)


def _clean_console_output(data):
    clean = _OSC_TITLE.sub('', data)
    clean = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', clean)
    # IOS XE can echo Ctrl-R as a control byte or as ^R before it
    # redisplays the current prompt. Treat that echo as a line boundary.
    return re.sub(r'\^R(?=[\w.()/:-]+[>#])', '\n', clean.replace('\x12', '\n'))


def _safe_read_only_nudge(output):
    """Allow Return only when the buffered console text is benign noise."""
    if _READ_ONLY_UNSAFE.search(output):
        return False

    for line in output.splitlines():
        line = line.replace('^R', '').strip()
        if not line:
            continue
        if re.fullmatch(
                r'(?:Trying .+\.\.\.|Connected to .+\.|Escape character is .+)',
                line):
            continue
        if re.match(
                r'^(?:\*?[A-Z][a-z]{2}\s+\d{1,2}\s+'
                r'\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+\S+)?\s*:\s*)?'
                r'%[A-Z0-9_]+-\d+-[A-Z0-9_]+:',
                line):
            continue
        if ('(config' not in line.lower()
                and re.fullmatch(r'[\w.()/:-]+[>#]', line)):
            continue
        return False
    return True


def _read_only_nudge_diagnostic(output):
    """Describe a rejected buffer without exposing any printable console text."""
    counts = {
        'blank': 0,
        'telnet': 0,
        'ctrl_r': 0,
        'syslog': 0,
        'exec': 0,
        'unsafe_interactive': 0,
        'config_prompt': 0,
        'unclassified': 0,
    }
    unclassified_lengths = []
    unclassified_has_controls = []
    control_codes = []
    lines = output.split('\n') if output else []

    for original in lines:
        stripped = original.strip(' 	')
        if not stripped:
            counts['blank'] += 1
            continue
        line = stripped.replace('^R', '').replace('\x12', '').strip(' 	')
        if not line:
            counts['ctrl_r'] += 1
        elif '(config' in line.lower():
            counts['config_prompt'] += 1
        elif _READ_ONLY_UNSAFE.search(line):
            counts['unsafe_interactive'] += 1
        elif re.fullmatch(
                r'(?:Trying .+\.\.\.|Connected to .+\.|Escape character is .+)',
                line):
            counts['telnet'] += 1
        elif re.match(
                r'^(?:\*?[A-Z][a-z]{2}\s+\d{1,2}\s+'
                r'\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\s+\S+)?\s*:\s*)?'
                r'%[A-Z0-9_]+-\d+-[A-Z0-9_]+:',
                line):
            counts['syslog'] += 1
        elif re.fullmatch(r'[\w.()/:-]+[>#]', line):
            counts['exec'] += 1
        else:
            codes = [f'U+{ord(char):04X}' for char in original
                     if ord(char) < 32 or 127 <= ord(char) <= 159]
            counts['unclassified'] += 1
            unclassified_lengths.append(len(original))
            unclassified_has_controls.append(bool(codes))
            control_codes.append(codes)

    fields = [f'characters={len(output)}', f'lines={len(lines)}']
    fields.extend(f'{name}={count}' for name, count in counts.items())
    fields.extend((
        'unclassified_lengths=' + json.dumps(unclassified_lengths, separators=(',', ':')),
        'unclassified_has_controls=' + json.dumps(
            unclassified_has_controls, separators=(',', ':')),
        'control_codes=' + json.dumps(control_codes, separators=(',', ':')),
    ))
    return ', '.join(fields)


class Console:
    def __init__(self, channel, boot_timeout=60):
        self.channel = channel
        self.prompt = None
        self.boot_timeout = boot_timeout
        self.pending = ''

    def send(self, line):
        self.channel.sendall(line + '\r')

    def expect(self, pattern, timeout=60, wake=False, latest=False, return_on_timeout=False, redisplay=False):
        data, self.pending = self.pending, ''
        started = time.monotonic()
        deadline = started + timeout
        next_wake = started + 10
        next_progress = started + 30
        while time.monotonic() < deadline:
            clean = _clean_console_output(data)
            matches = list(re.finditer(pattern, clean, re.M))
            match = matches[-1] if latest and matches else (matches[0] if matches else None)
            if match:
                self.pending = clean[match.end():]
                return clean[:match.end()], match
            now = time.monotonic()
            if (redisplay and now >= started + 2
                    and re.search(r'^[ \t]*[\w.()/:-]+#(?=[ \t]*[^ \t\n])', clean, re.M)):
                # Async startup/interface messages can overwrite an exec prompt.
                # Redisplay once without submitting input or repeating the command.
                self.channel.sendall('\x12')
                redisplay = False
            if wake and now >= next_wake:
                self.send('')
                next_wake = now + 10
            if now >= next_progress:
                print(f'Still waiting for console prompt ({int(now - started)}s elapsed); '
                      'Ctrl+C cancels. No console contents are logged.', file=sys.stderr, flush=True)
                next_progress = now + 30
            if self.channel.recv_ready():
                chunk = self.channel.recv(65536)
                if not chunk:
                    raise RuntimeError('Console closed')
                data += chunk.decode('utf-8', errors='replace').replace('\r', '')
            elif self.channel.closed or self.channel.exit_status_ready():
                raise RuntimeError('Console connection ended')
            else:
                time.sleep(.05)
        clean = _clean_console_output(data)
        if return_on_timeout:
            self.pending = clean
            return clean, None
        # Never include console output: it may contain passwords/configuration.
        raise RuntimeError('Timed out waiting for console prompt; inspect the EVE console for boot progress or an interactive setup prompt')

    def login(self, username, password, secret, *, read_only=False):
        if read_only:
            # Redisplay, never submit a pending command or a setup default.
            self.channel.sendall('\x12')
        else:
            self.send('')
        wake = not read_only
        secret_prompts = set()
        pattern = (r'(?i:Enter enable secret|Confirm enable secret)\s*:\s*$|'
                   r'Enter your selection\s*\[2\]\s*:\s*$|'
                   r'Username:\s*$|login:\s*$|Password:\s*$|Abort Power On Auto Provisioning[^\n]*[?:]|Do you want to enforce secure password standard[^\n]*[?:]|(?:Enter|Confirm) the password for [^\n]*admin[^\n]*:|Would you like to enter[^\n]*[?:]\s*$|'
                   r'Press RETURN to get started[^\n]*$|' + _PROMPT)
        probe = read_only
        for _ in range(12):
            if probe:
                observed, match = self.expect(
                    pattern, timeout=min(2, self.boot_timeout), wake=False,
                    latest=True, return_on_timeout=True)
                probe = False
                if match is None:
                    if _READ_ONLY_UNSAFE.search(observed) or not _safe_read_only_nudge(observed):
                        evidence = _read_only_nudge_diagnostic(observed)
                        raise RuntimeError(
                            'Read-only login refused Return because the console was not safely idle '
                            f'(classification: {evidence})')
                    self.send('')
                    continue
            else:
                observed, match = self.expect(
                    pattern, timeout=self.boot_timeout, wake=wake, latest=True)
            prompt = match.group().strip()
            if read_only and _READ_ONLY_UNSAFE.search(observed):
                raise RuntimeError('Read-only login refused interactive or configuration-mode prompt')
            if re.match(r'(Enter|Confirm) enable secret', prompt, re.I):
                stage = prompt.split()[0].lower()
                if stage in secret_prompts:
                    raise RuntimeError('Initial enable secret was rejected or confirmation failed; '
                                       'check CISCO_ENABLE_SECRET against the device password policy')
                if not secret or any(ord(char) < 32 or ord(char) == 127 for char in secret):
                    raise ValueError('CISCO_ENABLE_SECRET must be nonempty without control characters')
                secret_prompts.add(stage)
                wake = False
                print('Answering initial enable-secret ' + ('confirmation' if stage == 'confirm' else 'prompt') +
                      ' using CISCO_ENABLE_SECRET.', file=sys.stderr, flush=True)
                self.send(secret)
            elif prompt.startswith('Enter your selection'):
                wake = False
                self.send('2')  # Save the initial secret to NVRAM and exit setup.
            elif prompt.startswith('Username:') or prompt.lower().startswith('login:'):
                self.send(username)
                wake = False
            elif re.match(r'(?:Enter|Confirm) the password for .*admin', prompt, re.I):
                self.send(password)
                wake = False
            elif prompt.startswith('Password:'):
                self.send(password)
                wake = False
            elif re.match(r'Abort Power On Auto Provisioning', prompt, re.I):
                wake = False
                self.send('yes')
            elif re.match(r'Do you want to enforce secure password standard', prompt, re.I):
                wake = False
                self.send('yes')
            elif prompt.startswith('Would you like'):
                self.send('no')
            elif prompt.startswith('Press RETURN'):
                self.send('')
            elif prompt.endswith('>'):
                wake = False
                self.send('enable')
                _, enabled = self.expect(r'Password:\s*$|' + _PRIVILEGED_PROMPT)
                if enabled.group().strip().startswith('Password:'):
                    self.send(secret)
                else:
                    if read_only and '(config' in enabled.group():
                        raise RuntimeError('Read-only login refused configuration-mode prompt')
                    self.prompt = enabled.group().strip()
                    return
            elif '(config' in prompt:
                self.send('end')
            else:
                self.prompt = prompt
                return
        raise RuntimeError('Console login failed; check CISCO credentials')

    def command(self, command, timeout=60):
        self.send(command)
        output, match = self.expect(_PRIVILEGED_PROMPT, timeout, latest=True, redisplay=True)
        if re.search(r'^%\s*(?:Invalid|Incomplete|Ambiguous|Error|Authorization|Access denied)', output, re.M | re.I):
            raise RuntimeError('Cisco rejected a command; inspect the console (output omitted)')
        self.prompt = match.group().strip()
        lines = output[:match.start()].splitlines()
        if lines and lines[0].strip() == command:
            lines.pop(0)
        return '\n'.join(lines).strip() + '\n'

    def initialize(self, commands, username=None, password=None):
        if username is not None:
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', username):
                raise ValueError('Invalid Cisco username')
            if not password or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in password):
                raise ValueError('Cisco init password must be a nonempty CLI token')
        self.command('configure terminal')
        for index, command in enumerate(commands, start=1):
            try:
                self.command(command)
            except RuntimeError as error:
                raise RuntimeError(f'Cisco configuration command {index} failed: {error}') from error
        self.command('end')
        if username is not None:
            # Return to global configuration even if the file ends in a submode.
            self.command('configure terminal')
            self.command(f'username {username} privilege 15 password 0 {password}')
            self.command('line vty 0 4')
            self.command('login local')
            self.command('transport input ssh')
            self.command('end')
        saved = self.command('write memory', timeout=120)
        if '[OK]' not in saved:
            raise RuntimeError('Device did not confirm write memory; inspect startup-config')

    def backup(self):
        self.command('terminal length 0')
        config = self.command('more system:running-config', timeout=120)
        config = re.sub(r'\A.*?Using \d+ out of \d+ bytes\n', '', config, flags=re.S)
        if not re.search(r'^end\s*$', config, re.M):
            raise RuntimeError('Incomplete running configuration; backup not saved')
        return config

    def interface_status(self):
        """Read current primary IPv4 addresses without requesting DHCP leases."""
        self.command('terminal length 0')
        output = self.command('show ip interface brief')
        if not re.search(r'Interface\s+IP-Address\s+OK\?\s+Method\s+Status\s+Protocol', output):
            raise RuntimeError('Unrecognized interface status response')
        interfaces = []
        for line in output.splitlines():
            match = re.fullmatch(r'\s*(\S+)\s+(unassigned|\d+\.\d+\.\d+\.\d+)\s+(?:YES|NO)\s+(\S+)\s+(.+?)\s+(\S+)\s*', line)
            if not match:
                continue
            name, address, method, status, protocol = match.groups()
            interfaces.append({'interface': name,
                               'ip_address': None if address == 'unassigned' else str(IPv4Address(address)),
                               'method': method, 'status': status, 'protocol': protocol})
        if not interfaces:
            raise RuntimeError('No interfaces found in status response')
        return [interface for interface in interfaces if interface['ip_address'] is not None]


def environment_values(root):
    values = {}
    path = root / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition('=')
            if sep and not key.strip().startswith('#'):
                values[key.strip()] = value.strip()
    values.update(os.environ)
    return values


def credentials(root, prefix='CISCO'):
    values = environment_values(root)
    names = (prefix + '_USERNAME', prefix + '_PASSWORD')
    if prefix == 'CISCO':
        names += ('CISCO_ENABLE_SECRET',)
    if any(not values.get(name) for name in names):
        raise ValueError('Set ' + ', '.join(names) + ' in .env')
    return [values[name] for name in names]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'backup'))
    parser.add_argument('lab')
    parser.add_argument('node')
    parser.add_argument('--port', type=int, required=True, help='EVE Telnet console port for this node')
    parser.add_argument('--config', type=Path, help='IOS XE configuration-mode commands for init')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--server', default='default')
    args = parser.parse_args(argv)
    ssh = paramiko.SSHClient()
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError('Invalid console port')
        for name in (args.lab, args.node):
            if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]*', name):
                raise ValueError('Lab and node names must contain only letters, numbers, dots, underscores or hyphens')
        commands = []
        if args.action == 'init':
            if not args.config:
                raise ValueError('init requires --config containing configuration-mode commands')
            commands = [line.strip() for line in args.config.read_text().splitlines()
                        if line.strip() and not line.lstrip().startswith('!')]
            if not commands:
                raise ValueError('Configuration file is empty')
            if any(line.lower().startswith(('banner ', 'macro ')) for line in commands):
                raise ValueError('Multiline banner/macro configuration is not supported')
        elif args.config:
            raise ValueError('--config is only for init')
        login = credentials(args.root)
        server = load_server(args.root, args.server, auth='ssh')
        ssh.load_system_host_keys()
        ssh.connect(server.get('ssh_host') or urlsplit(server['url']).hostname,
                    username=server['ssh_username'], password=server['ssh_password'],
                    timeout=10, auth_timeout=10, banner_timeout=10,
                    allow_agent=False, look_for_keys=False)
        channel = ssh.get_transport().open_session(timeout=10)
        channel.get_pty(term='vt100', width=512, height=1000)
        channel.exec_command('telnet 127.0.0.1 ' + str(args.port))
        console = Console(channel)
        console.login(*login)
        if args.action == 'init':
            console.initialize(commands, username=login[0], password=login[1])
            print('Configuration applied and write memory completed for ' + args.node)
        else:
            config = console.backup()
            directory = args.root / 'labs' / args.lab / 'configs' / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
            directory.mkdir(parents=True, mode=0o700)
            filename = args.node + '.cfg'
            for name, content in ((filename, config), ('manifest.json', json.dumps({'saved': [
                    {'node': args.node, 'template': 'c8000v', 'file': filename}], 'source': 'console'}, indent=2) + '\n')):
                with (directory / name).open('x') as stream:
                    (directory / name).chmod(0o600)
                    stream.write(content)
            print('Backup saved: ' + str(directory))
    except (OSError, ValueError, RuntimeError, paramiko.SSHException):
        # Authentication/command output must never reveal credentials or configs.
        parser.exit(1, 'Error: Console operation failed; verify credentials, trusted host key, console port and config file. Partial init changes may remain; inspect the device before retrying.\n')
    finally:
        ssh.close()


if __name__ == '__main__':
    main()
