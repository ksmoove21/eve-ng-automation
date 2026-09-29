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
    if not isinstance(data, dict) or set(data) != {'hostname', 'management_interface', 'management_address', 'management_prefix_length', 'management_gateway', 'boot_image'}:
        raise ValueError('NX-OS bootstrap requires exactly hostname, management_interface, management_address, management_prefix_length, management_gateway, and boot_image')
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
    return [
        'hostname ' + data['hostname'],
        'interface ' + data['management_interface'],
        'ip address ' + str(address) + '/' + str(data['management_prefix_length']),
        'no cdp enable', 'exit',
        'boot nxos bootflash:' + data['boot_image'],
        'vrf context management',
        'ip route 0.0.0.0/0 ' + str(gateway), 'exit',
    ]

def load_bootstrap(path):
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as error:
        raise ValueError('Invalid NX-OS bootstrap YAML') from error
    return bootstrap_commands(data)

class NxosConsole(Console):
    """NX-OS configuration-mode initialization; credentials are shared CISCO_* values."""
    def initialize(self, commands, username=None, password=None):
        self.command('configure terminal')
        for index, command in enumerate(commands, start=1):
            try:
                self.command(command)
            except RuntimeError as error:
                raise RuntimeError(f"NX-OS configuration command {index} failed: {error}") from error
        self.command('end')
        saved = self.command('copy running-config startup-config', timeout=120)
        if re.search(r'%\s*(?:Invalid|Error|Failed)', saved, re.I):
            raise RuntimeError('NX-OS did not confirm copy running-config startup-config')
