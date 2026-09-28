"""Read-only NX-OS validation primitives for Nexus 9000v-style nodes."""
from ipaddress import IPv4Address, IPv4Interface, IPv4Network, ip_address
import re

FIELDS = {
    'nxos-interface': {'interface', 'admin_state', 'oper_state', 'address'},
    'nxos-vlan': {'vlan', 'state'}, 'nxos-vrf': {'vrf', 'expected'},
    'nxos-route': {'prefix', 'vrf', 'expected', 'next_hop'},
    'nxos-ping': {'destination', 'vrf', 'min_success_rate'},
    'nxos-vpc': {'state', 'peer_state', 'peer_link_state', 'consistency'},
    'nxos-port-channel': {'port_channel', 'oper_state', 'members'},
    'nxos-bgp-neighbor': {'neighbor', 'state', 'vrf', 'address_family'},
}
TOKEN = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\Z')
INTERFACE_TOKEN = re.compile(r'(?:Ethernet|Eth|port-channel|Po)\d+(?:/\d+){0,2}\Z', re.I)
BGP_STATES = {'idle', 'connect', 'active', 'opensent', 'openconfirm', 'established'}

def _token(value, field):
    if not isinstance(value, str) or not TOKEN.fullmatch(value): raise ValueError(field + ' must be a single CLI token')
def _interface_token(value, field):
    if not isinstance(value, str) or not INTERFACE_TOKEN.fullmatch(value): raise ValueError(field + ' must be an NX-OS interface name')
def _clean(text):
    if not isinstance(text, str): raise RuntimeError('Unrecognized or incomplete NX-OS response')
    text = text.replace('\r\n', '\n').replace('\r', '\n').rstrip()
    if not text or re.search(r'--More--|^\s*%', text, re.M): raise RuntimeError('Unrecognized or incomplete NX-OS response')
    return text
def validate_check(c):
    kind = c['type']
    if kind == 'nxos-interface':
        _interface_token(c.get('interface'), 'interface')
        for key in ('admin_state', 'oper_state'):
            if key in c and c[key].lower() not in ('up', 'down'): raise ValueError(key + ' must be up or down')
        if 'address' in c: IPv4Interface(c['address'])
    elif kind == 'nxos-vlan':
        if type(c.get('vlan')) is not int or not 1 <= c['vlan'] <= 4094: raise ValueError('vlan must be an integer from 1 to 4094')
        if 'state' in c: _token(c['state'], 'state')
    elif kind == 'nxos-vrf':
        _token(c.get('vrf'), 'vrf')
        if c.get('expected', 'present') not in ('present', 'absent'): raise ValueError('expected must be present or absent')
    elif kind == 'nxos-route':
        if not isinstance(c.get('prefix'), str) or '/' not in c['prefix'] or str(IPv4Network(c['prefix'], strict=True)) != c['prefix']: raise ValueError('prefix must be canonical IPv4 CIDR')
        if c.get('expected') not in ('present', 'absent'): raise ValueError('expected must be present or absent')
        if 'vrf' in c: _token(c['vrf'], 'vrf')
        if 'next_hop' in c:
            if c['expected'] == 'absent': raise ValueError('next_hop applies only to present routes')
            IPv4Address(c['next_hop'])
    elif kind == 'nxos-ping':
        IPv4Address(c.get('destination'))
        if 'vrf' in c: _token(c['vrf'], 'vrf')
        if type(c.get('min_success_rate', 100)) is not int or not 0 <= c.get('min_success_rate', 100) <= 100: raise ValueError('min_success_rate must be an integer from 0 to 100')
    elif kind == 'nxos-vpc':
        keys = ('state', 'peer_state', 'peer_link_state', 'consistency')
        if not any(key in c for key in keys): raise ValueError('nxos-vpc requires an expected state')
        if any(c[key].lower() not in ('up', 'down') for key in keys if key in c): raise ValueError('vPC states must be up or down')
    elif kind == 'nxos-port-channel':
        _token(c.get('port_channel'), 'port_channel')
        if 'oper_state' in c and c['oper_state'].lower() not in ('up', 'down'): raise ValueError('oper_state must be up or down')
        if 'members' in c:
            if not isinstance(c['members'], list) or not c['members']: raise ValueError('members must be a nonempty list')
            for value in c['members']: _interface_token(value, 'port-channel member')
    else:
        family = c.get('address_family', 'ipv4-unicast')
        if family not in ('ipv4-unicast', 'ipv6-unicast'): raise ValueError('address_family must be ipv4-unicast or ipv6-unicast')
        if ip_address(c.get('neighbor')).version != (4 if family.startswith('ipv4') else 6): raise ValueError('neighbor must match address_family')
        if c.get('state', '').lower() not in BGP_STATES: raise ValueError('Unsupported BGP state')
        if 'vrf' in c: _token(c['vrf'], 'vrf')

def command_for(c):
    kind = c['type']
    if kind == 'nxos-interface': return 'show interface ' + c['interface']
    if kind == 'nxos-vlan': return 'show vlan id ' + str(c['vlan'])
    if kind == 'nxos-vrf': return 'show vrf'
    if kind == 'nxos-route': return 'show ip route' + (' vrf ' + c['vrf'] if 'vrf' in c else '') + ' ' + c['prefix']
    if kind == 'nxos-ping': return 'ping' + (' vrf ' + c['vrf'] if 'vrf' in c else '') + ' ' + c['destination'] + ' count 5 timeout 2'
    if kind == 'nxos-vpc': return 'show vpc brief'
    if kind == 'nxos-port-channel': return 'show interface ' + c['port_channel']
    return 'show bgp' + (' vrf ' + c['vrf'] if 'vrf' in c else '') + ' ' + c.get('address_family', 'ipv4-unicast').replace('-', ' ') + ' summary'

def _interface(text):
    text = _clean(text); op = re.search(r'^\s*(\S+) is (up|down|administratively down)[ \t]*$', text, re.M | re.I); admin = re.search(r'admin state is (up|down)', text, re.I)
    if not op or not admin: raise RuntimeError('Unrecognized NX-OS interface response')
    address = re.search(r'Internet Address is (\d+\.\d+\.\d+\.\d+/\d+)', text, re.I)
    return {'interface': op.group(1), 'admin_state': admin.group(1).lower(), 'oper_state': 'up' if op.group(2).lower() == 'up' else 'down', 'address': str(IPv4Interface(address.group(1))) if address else None}
def _vlan(text):
    text = _clean(text)
    if not re.search(r'^\s*VLAN\s+Name\s+Status\s+Ports[ \t]*$', text, re.M | re.I): raise RuntimeError('Unrecognized NX-OS VLAN response')
    rows = re.findall(r'^\s*(\d+)\s+\S+\s+(\S+)\s*.*\Z', text, re.M)
    if len(rows) != 1: raise RuntimeError('Unrecognized NX-OS VLAN row')
    return int(rows[0][0]), rows[0][1].lower()
def _route(text):
    if re.fullmatch(r'\s*% Route not found\s*', text, re.I): return False, None, []
    text = _clean(text); rows = re.findall(r'^\s*(\d+\.\d+\.\d+\.\d+/\d+),\s+ubest/mbest:', text, re.M)
    if len(rows) != 1: raise RuntimeError('Unrecognized NX-OS route response')
    return True, str(IPv4Network(rows[0], strict=True)), sorted({str(IPv4Address(x)) for x in re.findall(r'\bvia (\d+\.\d+\.\d+\.\d+)', text)})
def _ping(text):
    text = _clean(text); rows = re.findall(r'(\d+(?:\.\d+)?)%\s*\((\d+)/(\d+)\)', text)
    if len(rows) != 1 or int(rows[0][2]) != 5 or float(rows[0][0]) != int(rows[0][1]) * 20: raise RuntimeError('Unrecognized NX-OS ping result')
    return int(float(rows[0][0]))
def _vpc(text):
    text = _clean(text)
    def state(pattern):
        found = re.search(pattern, text, re.I | re.M)
        if not found: raise RuntimeError('Unrecognized NX-OS vPC response')
        return 'up' if re.search(r'up|enabled|ok|success|formed', found.group(1), re.I) else 'down'
    link = re.search(r'^\s*\d+\s+Po\d+\s+(up|down)\b', text, re.I | re.M)
    if not link: raise RuntimeError('Unrecognized NX-OS vPC peer-link response')
    return {'state': state(r'^\s*vPC status\s*:\s*(.+)$'), 'peer_state': state(r'^\s*Peer status\s*:\s*(.+)$'), 'peer_link_state': link.group(1).lower(), 'consistency': state(r'^\s*Configuration consistency status\s*:\s*(.+)$')}
def _bgp(text):
    text = _clean(text); header = re.search(r'^\s*Neighbor\s+.*State/PfxRcd[ \t]*$', text, re.M | re.I)
    if not header: raise RuntimeError('Unrecognized NX-OS BGP summary')
    rows = []
    for line in text[header.end():].splitlines():
        if not line.strip(): continue
        values = line.split()
        if len(values) < 10: raise RuntimeError('Malformed NX-OS BGP row')
        state = 'established' if values[-1].isdecimal() else values[-1].lower()
        if state not in BGP_STATES: raise RuntimeError('Unrecognized NX-OS BGP state')
        rows.append((str(ip_address(values[0])), state))
    return rows

def evaluate(console, c):
    validate_check(c); command = command_for(c); evidence = {'command': command, 'expected': {k:v for k,v in c.items() if k not in ('name','node','type','required')}}
    try:
        kind = c['type']
        if kind == 'nxos-interface':
            seen = _interface(console.command(command)); evidence['observed'] = seen; passed = all(seen[k] == (v if k == 'address' else v.lower()) for k,v in c.items() if k in ('admin_state','oper_state','address'))
        elif kind == 'nxos-vlan':
            seen = _vlan(console.command(command)); evidence['observed'] = {'vlan':seen[0], 'state':seen[1]}; passed = seen[0] == c['vlan'] and ('state' not in c or seen[1] == c['state'].lower())
        elif kind == 'nxos-vrf':
            text = console.command(command); text = _clean(text); present = bool(re.search(r'^\s*' + re.escape(c['vrf']) + r'\s+\d+\s+', text, re.M)); evidence['observed'] = {'present': present}; passed = present == (c.get('expected','present') == 'present')
        elif kind == 'nxos-route':
            seen = _route(console.command(command)); evidence['observed'] = {'present':seen[0], 'prefix':seen[1], 'next_hops':seen[2]}; present = seen[0] and seen[1] == c['prefix']; passed = present == (c['expected'] == 'present') and ('next_hop' not in c or c['next_hop'] in seen[2])
        elif kind == 'nxos-ping':
            results = [_ping(console.command(command, timeout=30))]; minimum = c.get('min_success_rate',100)
            if results[0] < minimum: results.append(_ping(console.command(command, timeout=30)))
            evidence['success_rate'] = max(results); evidence['attempts'] = results; passed = max(results) >= minimum
        elif kind == 'nxos-vpc':
            seen = _vpc(console.command(command)); evidence['observed'] = seen; passed = all(seen[k] == v.lower() for k,v in c.items() if k in seen)
        elif kind == 'nxos-port-channel':
            text = console.command(command); text = _clean(text); found = re.search(r'^\s*(Po\d+)\s+is\s+(up|down)[ \t]*$', text, re.M|re.I)
            if not found: raise RuntimeError('Unrecognized NX-OS port-channel response')
            passed = found.group(2).lower() == c.get('oper_state', found.group(2)).lower(); evidence['observed'] = {'port_channel':found.group(1),'oper_state':found.group(2).lower()}
            if 'members' in c:
                summary = _clean(console.command('show port-channel summary')); members = re.findall(r'\b((?:Ethernet|Eth)\d+/\d+(?:/\d+)?)\([A-Z]\)', next((line for line in summary.splitlines() if re.search(r'\b' + re.escape(c['port_channel']) + r'\(', line, re.I)), ''), re.I); evidence['members'] = members; passed = passed and set(members) == set(c['members'])
        else:
            seen = _bgp(console.command(command)); evidence['observed'] = seen; target = str(ip_address(c['neighbor'])); passed = bool([x for x in seen if x[0] == target and x[1] == c['state'].lower()])
        if not passed: evidence['reason'] = 'Observed result does not match acceptance criteria'
        return passed, evidence
    except RuntimeError as error:
        evidence['reason'] = str(error); return False, evidence
