"""NX-OS bootstrap intent rendering and console save semantics."""
from ipaddress import IPv4Address
import re
import yaml
from .device_console import Console

_TOKEN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\Z')
_IMAGE = re.compile(r'[A-Za-z0-9_.-]+\Z')

def _token(value, field, pattern=_TOKEN):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(field + ' must be a safe single CLI token')

def bootstrap_commands(data):
    """Render explicit NX-OS management bootstrap intent; no private defaults."""
    required = {'hostname', 'management_interface', 'management_address', 'management_prefix_length', 'management_gateway', 'boot_image'}
    if not isinstance(data, dict) or not required <= set(data) or set(data) - required - {'enable_lacp'}:
        raise ValueError('NX-OS bootstrap requires management and boot fields, with optional enable_lacp')
    if type(data.get('enable_lacp', False)) is not bool:
        raise ValueError('enable_lacp must be a boolean')
    _token(data['hostname'], 'hostname')
    _token(data['management_interface'], 'management_interface', re.compile(r'(?:mgmt\d+|Management\d+)\Z'))
    _token(data['boot_image'], 'boot_image', _IMAGE)
    if type(data['management_prefix_length']) is not int or not 1 <= data['management_prefix_length'] <= 32:
        raise ValueError('management_prefix_length must be an integer from 1 to 32')
    try:
        address = IPv4Address(data['management_address'])
        gateway = IPv4Address(data['management_gateway'])
    except ValueError:
        raise ValueError('management_address and management_gateway must be IPv4 addresses') from None
    commands = [
        'hostname ' + data['hostname'],
        'interface ' + data['management_interface'],
        'ip address ' + str(address) + '/' + str(data['management_prefix_length']),
        'no cdp enable', 'exit',
        'boot nxos bootflash:' + data['boot_image'],
        'vrf context management',
        'ip route 0.0.0.0/0 ' + str(gateway), 'exit',
    ]
    if data.get('enable_lacp'):
        commands.append('feature lacp')
    return commands

def load_bootstrap(path):
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ValueError('Invalid NX-OS bootstrap YAML') from error
    return bootstrap_commands(data)

class NxosConsole(Console):
    """NX-OS configuration-mode initialization; credentials are shared CISCO_* values."""
    def initialize(self, commands, username=None, password=None):
        self.command('terminal length 0', require_echo=True)
        boot_state = self.command('show boot variables', require_echo=True)
        if re.search(r'%\s*(?:Invalid|Error|Failed)', boot_state, re.I):
            raise RuntimeError('NX-OS boot variables are unavailable')
        boot_commands = [command for command in commands if command.startswith('boot nxos bootflash:')]
        if len(boot_commands) != 1:
            raise ValueError('NX-OS bootstrap requires exactly one boot image')
        expected_image = boot_commands[0].split('bootflash:', 1)[1]
        boot_matches = re.search(r'(?<![A-Za-z0-9_.-])' + re.escape(expected_image) +
                                 r'(?![A-Za-z0-9_.-])', boot_state) is not None
        self.command('configure terminal', require_echo=True)
        for index, command in enumerate(commands, start=1):
            if command == boot_commands[0] and boot_matches:
                continue
            try:
                self.command(command, require_echo=True)
            except RuntimeError as error:
                raise RuntimeError(f"NX-OS configuration command {index} failed: {error}") from error
        self.command('end', require_echo=True)
        self.command('terminal length 0', require_echo=True)
        saved = self.command('copy running-config startup-config', timeout=120,
                             require_echo=True)
        if re.search(r'%\s*(?:Invalid|Error|Failed)', saved, re.I):
            raise RuntimeError('NX-OS did not confirm copy running-config startup-config')
        startup = self.command('show startup-config', timeout=120,
                               require_echo=True)
        required = [command for command in commands if command.startswith(
            ('hostname ', 'ip address ', 'ip route 0.0.0.0/0 '))]
        if any(command not in startup for command in required):
            raise RuntimeError('NX-OS startup-config lacks declared management bootstrap')
