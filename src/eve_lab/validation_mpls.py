"""Read-only IPv4 LDP and LFIB acceptance for IOS-family guests."""
from ipaddress import IPv4Address, IPv4Network
import re

FIELDS = {
    'ldp-neighbor': {'neighbor', 'state'},
    'mpls-forwarding': {'prefix', 'expected', 'next_hop', 'action'},
}


def validate_check(check):
    if check['type'] == 'ldp-neighbor':
        if not isinstance(check.get('neighbor'), str):
            raise ValueError('LDP neighbor must be an IPv4 address string')
        IPv4Address(check['neighbor'])
        if check.get('state') != 'operational':
            raise ValueError('LDP acceptance supports operational state only')
        return
    if not isinstance(check.get('prefix'), str):
        raise ValueError('MPLS prefix must be a canonical IPv4 network string')
    network = IPv4Network(check['prefix'], strict=True)
    if str(network) != check['prefix']:
        raise ValueError('MPLS prefix must use canonical CIDR notation')
    if check.get('expected') not in ('present', 'absent'):
        raise ValueError('MPLS forwarding expected must be present or absent')
    if 'next_hop' in check:
        if not isinstance(check['next_hop'], str):
            raise ValueError('MPLS next hop must be an IPv4 address string')
        IPv4Address(check['next_hop'])
    if 'action' in check and check['action'] not in ('swap', 'pop'):
        raise ValueError('MPLS forwarding action must be swap or pop')
    if check['expected'] == 'absent' and ('next_hop' in check or 'action' in check):
        raise ValueError('MPLS next_hop/action require expected present')


def _clean(output):
    if not output.strip() or re.search(r'--More--|^\s*%', output, re.M):
        raise RuntimeError('Unrecognized or incomplete IOS MPLS response')


def parse_ldp(output):
    _clean(output)
    blocks = re.split(r'(?m)(?=^\s*Peer LDP Ident:)', output)
    rows = []
    for block in blocks:
        if not block.strip():
            continue
        peer = re.search(r'Peer LDP Ident:\s*(\S+):(\d+);\s*Local LDP Ident:?\s*(\S+):(\d+)', block)
        state = re.search(r'\bState:\s*([A-Za-z]+);', block)
        if (not peer or not state or 'TCP connection:' not in block
                or 'Up time:' not in block or 'LDP discovery sources:' not in block):
            raise RuntimeError('Incomplete LDP neighbor block')
        try:
            neighbor, local = str(IPv4Address(peer[1])), str(IPv4Address(peer[3]))
        except ValueError:
            raise RuntimeError('Invalid LDP router identity') from None
        rows.append({'neighbor': neighbor, 'local': local,
                     'label_space': int(peer[2]), 'local_label_space': int(peer[4]),
                     'state': 'operational' if state[1].lower() == 'oper' else state[1].lower()})
    if not rows:
        raise RuntimeError('No recognized LDP neighbor blocks')
    return rows


def parse_lfib(output):
    _clean(output)
    header = re.search(r'(?m)^\s*Local\s+Outgoing\s+Prefix\s+Bytes [Ll]abel\s+Outgoing\s+Next Hop\s*\n\s*Label\s+Label(?: or VC)?(?: or Tunnel Id)?\s+.*(?:Switched|switched)\s+interface\s*$', output)
    if not header:
        raise RuntimeError('Unrecognized IPv4 LFIB header')
    rows = []
    for line in output[header.end():].splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(\d+)\s+(\d+|Pop [Ll]abel|No [Ll]abel)\s+(\S+)\s+(\d+)\s+(\S+)\s+(\S+)\s*', line)
        if not match:
            raise RuntimeError('Unsupported or incomplete IPv4 LFIB row')
        try:
            prefix = str(IPv4Network(match[3], strict=True))
            hop = str(IPv4Address(match[6]))
        except ValueError:
            raise RuntimeError('Invalid IPv4 LFIB prefix or next hop') from None
        local = int(match[1])
        outgoing = match[2]
        if local > 1048575 or (outgoing.isdecimal() and int(outgoing) > 1048575):
            raise RuntimeError('Invalid MPLS label value')
        action = 'swap' if outgoing.isdecimal() else 'pop' if outgoing.lower() == 'pop label' else 'unlabeled'
        rows.append({'prefix': prefix, 'local_label': local, 'outgoing_label': outgoing,
                     'action': action, 'bytes_switched': int(match[4]),
                     'interface': match[5], 'next_hop': hop})
    return rows


def command_for(check):
    return 'show mpls ldp neighbor' if check['type'] == 'ldp-neighbor' else 'show mpls forwarding-table'


def evaluate(console, check):
    validate_check(check)
    command = command_for(check)
    evidence = {'command': command, 'expected': {k: v for k, v in check.items()
                if k not in ('name', 'node', 'type', 'required')}}
    try:
        output = console.command(command, require_echo=True)
        if check['type'] == 'ldp-neighbor':
            matches = [row for row in parse_ldp(output) if row['neighbor'] == check['neighbor']
                       and row['label_space'] == 0 and row['local_label_space'] == 0]
            passed = bool(matches) and all(row['state'] == 'operational' for row in matches)
        else:
            matches = [row for row in parse_lfib(output) if row['prefix'] == check['prefix']]
            labeled = [row for row in matches if row['action'] in ('swap', 'pop')]
            passed = bool(labeled) == (check['expected'] == 'present')
            if 'next_hop' in check:
                passed = passed and any(row['next_hop'] == check['next_hop'] and
                    ('action' not in check or row['action'] == check['action']) for row in labeled)
            elif 'action' in check:
                passed = passed and bool(labeled) and all(row['action'] == check['action'] for row in labeled)
        evidence['observed'] = matches
        if not passed:
            evidence['reason'] = 'Observed result does not match acceptance criteria'
        return passed, evidence
    except RuntimeError as error:
        evidence['reason'] = str(error)
        return False, evidence
