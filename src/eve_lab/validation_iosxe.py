"""IOS XE acceptance commands and parsers; no configuration operations.

Only c8000v is enabled by the orchestrator. New platform adapters must provide
explicit capabilities rather than inheriting IOS syntax by template guessing.
"""
from ipaddress import IPv4Address, IPv4Network, ip_address
import re
from . import validation_kg


FIELDS = {
    'route': {'prefix', 'vrf', 'expected', 'next_hop'},
    'default-route': {'vrf', 'expected'},
    'bgp-neighbor': {'neighbor', 'state', 'vrf', 'address_family'},
    'ospf-neighbor': {'neighbor', 'state'},
    'isis-adjacency': {'neighbor', 'state'},
    'vrf-ping': {'vrf', 'destination', 'min_success_rate'},
    'mtu-ping': {'destination', 'packet_size', 'df', 'min_success_rate'},
}
FIELDS.update(validation_kg.FIELDS)
FIELDS.update({"iosxe-vlan": {"vlan"}, "iosxe-switchport": {"interface", "mode", "vlans"}})
BGP_STATES = {'idle', 'connect', 'active', 'opensent', 'openconfirm', 'established'}
OSPF_STATES = {'down', 'attempt', 'init', '2way', 'exstart', 'exchange', 'loading', 'full'}


def _token(value, field):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', value):
        raise ValueError(field + ' must be a single CLI token (letters, digits, _, ., -)')


def validate_check(check):
    """Reject unsupported intent before connecting; never normalize caller data."""
    kind = check['type']
    if kind in validation_kg.FIELDS:
        return validation_kg.validate_check(check)
    if kind == "iosxe-vlan":
        if type(check.get("vlan")) is not int or not 1 <= check["vlan"] <= 4094:
            raise ValueError("vlan must be an integer from 1 to 4094")
        return
    if kind == "iosxe-switchport":
        if not isinstance(check.get("interface"), str) or not re.fullmatch(r"GigabitEthernet1/0/[1-9][0-9]*", check["interface"]):
            raise ValueError("Invalid switchport interface")
        if check.get("mode") not in ("access", "trunk") or not isinstance(check.get("vlans"), list) or not check["vlans"]:
            raise ValueError("Switchport requires mode and vlans")
        if any(type(v) is not int or not 1 <= v <= 4094 for v in check["vlans"]):
            raise ValueError("Invalid switchport VLAN")
        if check["mode"] == "access" and len(check["vlans"]) != 1: raise ValueError("Access port requires one VLAN")
        return
    if 'vrf' in check or kind == 'vrf-ping':
        _token(check.get('vrf'), 'vrf')
    if kind in ('route', 'default-route'):
        if check.get('expected') not in ('present', 'absent'):
            raise ValueError('Route expected must be present or absent')
        if kind == 'route':
            if not isinstance(check.get('prefix'), str) or '/' not in check['prefix']:
                raise ValueError('Route prefix must be an IPv4 CIDR network')
            if str(IPv4Network(check['prefix'], strict=True)) != check['prefix']:
                raise ValueError('Route prefix must use canonical IPv4 CIDR notation')
        if 'next_hop' in check:
            if not isinstance(check['next_hop'], str):
                raise ValueError('next_hop must be an IPv4 address string')
            IPv4Address(check['next_hop'])
            if check['expected'] == 'absent':
                raise ValueError('next_hop applies only to expected present routes')
    elif kind in ('bgp-neighbor', 'ospf-neighbor', 'isis-adjacency'):
        _token(check.get('state'), 'state')
        state = check['state'].lower()
        allowed = BGP_STATES if kind == 'bgp-neighbor' else OSPF_STATES if kind == 'ospf-neighbor' else {'up', 'down', 'init'}
        if state not in allowed:
            raise ValueError('Unsupported adjacency state for ' + kind)
        if kind == 'isis-adjacency':
            _token(check.get('neighbor'), 'neighbor')
        else:
            if not isinstance(check.get('neighbor'), str):
                raise ValueError('neighbor must be an address string')
            (ip_address if kind == 'bgp-neighbor' else IPv4Address)(check['neighbor'])
        if kind == 'bgp-neighbor':
            family = check.get('address_family', 'ipv4-unicast')
            if family not in ('ipv4-unicast', 'ipv6-unicast'):
                raise ValueError('BGP supports ipv4-unicast and ipv6-unicast only')
            if ip_address(check['neighbor']).version != (4 if family == 'ipv4-unicast' else 6):
                raise ValueError('BGP neighbor address must match address_family')
    else:
        if not isinstance(check.get('destination'), str):
            raise ValueError('destination must be an IPv4 address string')
        IPv4Address(check['destination'])
        rate = check.get('min_success_rate', 100)
        if type(rate) is not int or not 0 <= rate <= 100:
            raise ValueError('min_success_rate must be an integer from 0 to 100')
        if kind == 'mtu-ping':
            if type(check.get('packet_size')) is not int or not 36 <= check['packet_size'] <= 18024:
                raise ValueError('packet_size must be an integer from 36 to 18024 (IP datagram bytes)')
            if type(check.get('df')) is not bool:
                raise ValueError('df must be a boolean')


def _clean(output):
    if not output.strip() or re.search(r'--More--|^\s*%', output, re.M):
        raise RuntimeError('Unrecognized or incomplete IOS XE response')
    return output


def parse_route(output):
    """Parse a single exact IPv4 route detail, including all ECMP next hops."""
    absent = re.fullmatch(r'\s*(?:Routing Table: [^\n]+\n\s*)?% (?:Network|Subnet) not in table\s*', output)
    if absent:
        return {'prefix': None, 'next_hops': [], 'present': False}
    _clean(output)
    headers = re.findall(r'^\s*Routing entry for (\S+?)(?:,.*)?\s*$', output, re.M)
    if len(headers) != 1 or not re.search(r'^\s*Known via "[^"\n]+"', output, re.M):
        raise RuntimeError('Unrecognized route detail')
    try:
        prefix = str(IPv4Network(headers[0], strict=True))
    except ValueError:
        raise RuntimeError('Invalid route prefix in response') from None
    parts = output.split('Routing Descriptor Blocks:')
    if len(parts) != 2:
        raise RuntimeError('Missing route descriptors')
    descriptors = re.findall(r'^\s*\*?\s*(\d+\.\d+\.\d+\.\d+|directly connected)(?:,.*)?\s*$', parts[1], re.M)
    metrics = re.findall(r'^\s*Route metric is \d+,', parts[1], re.M)
    if not descriptors or len(metrics) != len(descriptors):
        raise RuntimeError('Incomplete route descriptors')
    try:
        hops = sorted({str(IPv4Address(value)) for value in descriptors if value != 'directly connected'})
    except ValueError:
        raise RuntimeError('Invalid route next hop in response') from None
    return {'prefix': prefix, 'next_hops': hops, 'present': True}


def parse_bgp(output):
    """Parse scoped IOS XE BGP summary rows; a prefix count means Established."""
    _clean(output)
    header = re.search(r'^\s*Neighbor\s+V\s+AS\s+MsgRcvd\s+MsgSent\s+TblVer\s+InQ\s+OutQ\s+Up/Down\s+State/PfxRcd\s*$', output, re.M)
    if not header:
        raise RuntimeError('Unrecognized BGP summary')
    rows = []
    pending = ''
    for line in output[header.end():].splitlines():
        if not line.strip():
            continue
        fields = (pending + ' ' + line.strip()).split()
        if len(fields) == 1 and not pending:
            pending = fields[0]
            continue
        pending = ''
        if (len(fields) < 10 or fields[1] != '4'
                or not re.fullmatch(r'\d+(?:\.\d+)?', fields[2])
                or not all(v.isdecimal() for v in fields[3:8])):
            raise RuntimeError('Malformed BGP summary row')
        try:
            neighbor = str(ip_address(fields[0]))
        except ValueError:
            raise RuntimeError('Invalid BGP neighbor in response') from None
        raw = ' '.join(fields[9:])
        if not re.fullmatch(r'\d+|[A-Za-z]+(?:\s*\([A-Za-z]+\))?', raw):
            raise RuntimeError('Malformed BGP state')
        state = 'established' if raw.isdecimal() else raw.split('(')[0].strip().lower()
        if state not in BGP_STATES:
            raise RuntimeError('Unrecognized BGP state')
        rows.append({'neighbor': neighbor, 'state': state, 'reported_state': raw,
                     'prefixes_received': int(raw) if raw.isdecimal() else None})
    if pending:
        raise RuntimeError('Truncated BGP summary row')
    return rows


def parse_ospf(output):
    _clean(output)
    header = re.search(r'^\s*Neighbor ID\s+Pri\s+State\s+Dead Time\s+Address\s+Interface\s*$', output, re.M)
    if not header:
        raise RuntimeError('Unrecognized OSPF neighbor table')
    rows = []
    for line in output[header.end():].splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(\S+)\s+(\d+)\s+([A-Za-z0-9]+)(?:/\s*([A-Za-z-]+))?\s+(\S+)\s+(\S+)\s+(\S+)\s*', line)
        if not match:
            raise RuntimeError('Malformed OSPF neighbor row')
        neighbor, priority, raw_state, role, dead_time, address, interface = match.groups()
        state = raw_state.lower()
        if state not in OSPF_STATES or (role is not None and role.upper() not in ('DR', 'BDR', 'DROTHER', '-')):
            raise RuntimeError('Unrecognized OSPF state')
        try:
            neighbor, address = str(IPv4Address(neighbor)), str(IPv4Address(address))
        except ValueError:
            raise RuntimeError('Invalid OSPF address in response') from None
        rows.append({'neighbor': neighbor, 'address': address, 'state': state,
                     'reported_state': raw_state + ('/' + role if role else ''),
                     'priority': int(priority), 'dead_time': dead_time, 'interface': interface})
    return rows


def parse_isis(output):
    _clean(output)
    header = re.search(r'^\s*System Id\s+Type\s+Interface\s+IP Address\s+State\s+Holdtime\s+Circuit Id\s*$', output, re.M | re.I)
    if not header:
        raise RuntimeError('Unrecognized IS-IS neighbor table')
    rows = []
    for line in output[header.end():].splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(\S+)\s+(L1|L2|L1L2)\s+(\S+)\s+(?:(\d+\.\d+\.\d+\.\d+)\s+)?(UP|DOWN|INIT)\s+(\d+)\s+(\S+)\s*', line, re.I)
        if not match:
            raise RuntimeError('Malformed IS-IS neighbor row')
        neighbor, level, interface, address, state, holdtime, circuit = match.groups()
        if address:
            try:
                address = str(IPv4Address(address))
            except ValueError:
                raise RuntimeError('Invalid IS-IS address in response') from None
        rows.append({'neighbor': neighbor, 'state': state.lower(), 'level': level,
                     'interface': interface, 'address': address, 'holdtime': int(holdtime),
                     'circuit_id': circuit})
    return rows


def parse_isis_hostnames(output):
    """Resolve numeric system IDs when IOS displays dynamic hostnames."""
    _clean(output)
    header = re.search(r'^\s*Level\s+System ID\s+Dynamic Hostname(?:\s+\([^\n]+\))?\s*$', output, re.M)
    if not header:
        raise RuntimeError('Unrecognized IS-IS hostname table')
    rows = []
    for line in output[header.end():].splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r'\s*(?:[12]|\*)\s+([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4})\s+(\S+)\s*', line)
        if not match:
            raise RuntimeError('Malformed IS-IS hostname row')
        rows.append({'system_id': match[1].lower(), 'hostname': match[2]})
    return rows


def parse_ping(output):
    _clean(output)
    matches = re.findall(r'^\s*Success rate is\s+(\d+)\s+percent\s+\((\d+)/(\d+)\)(?:,.*)?\s*$', output, re.M)
    if len(matches) != 1:
        raise RuntimeError('Unrecognized ping result')
    rate, received, sent = map(int, matches[0])
    if sent != 5 or not 0 <= received <= sent or rate != received * 100 // sent:
        raise RuntimeError('Inconsistent ping result')
    return {'success_rate': rate, 'received': received, 'sent': sent}


def command_for(check):
    kind = check['type']
    if kind in ('route', 'default-route'):
        network = IPv4Network(check['prefix'] if kind == 'route' else '0.0.0.0/0')
        scope = ' vrf ' + check['vrf'] if 'vrf' in check else ''
        return f'show ip route{scope} {network.network_address} {network.netmask}'
    if kind == 'bgp-neighbor':
        family = check.get('address_family', 'ipv4-unicast').split('-')[0]
        scope = family + ' unicast'
        if 'vrf' in check:
            scope = ('vpnv4' if family == 'ipv4' else 'vpnv6') + ' unicast vrf ' + check['vrf']
        return 'show bgp ' + scope + ' summary'
    if kind == 'ospf-neighbor':
        return 'show ip ospf neighbor'
    if kind == 'isis-adjacency':
        return 'show isis neighbors'
    scope = ' vrf ' + check['vrf'] if kind == 'vrf-ping' else ''
    command = 'ping' + scope + ' ' + check['destination'] + ' repeat 5 timeout 2'
    if kind == 'mtu-ping':
        command += ' size ' + str(check['packet_size'])
        if check['df']:
            command += ' df-bit'
    return command


def evaluate(console, check):
    """Return measured evidence, failing closed on unsupported output."""
    if check["type"] in validation_kg.FIELDS:
        return validation_kg.evaluate(console, check)
    validate_check(check)
    if check["type"] in ("iosxe-vlan", "iosxe-switchport"):
        return _evaluate_l2(console, check)
    command = command_for(check)
    evidence = {'command': command, 'expected': {k: v for k, v in check.items()
                                                if k not in ('name', 'node', 'type', 'required')}}
    try:
        kind = check['type']
        if kind in ('vrf-ping', 'mtu-ping'):
            minimum = check.get('min_success_rate', 100)
            from .reachability import retry_ping
            passed, best, attempts = retry_ping(
                lambda: parse_ping(console.command(command, timeout=30)), minimum)
            evidence.update(destination=check['destination'], success_rate=best,
                            minimum_success_rate=minimum, attempts=attempts)
        else:
            output = console.command(command)
            if kind in ('route', 'default-route'):
                observed = parse_route(output)
                prefix = check['prefix'] if kind == 'route' else '0.0.0.0/0'
                # A covering route is not evidence of this exact prefix.
                present = observed['present'] and observed['prefix'] == prefix
                passed = present == (check['expected'] == 'present')
                if 'next_hop' in check:
                    passed = passed and check['next_hop'] in observed['next_hops']
                evidence.update(prefix=prefix, present=present, observed=observed)
            else:
                parser = {'bgp-neighbor': parse_bgp, 'ospf-neighbor': parse_ospf,
                          'isis-adjacency': parse_isis}[kind]
                rows = parser(output)
                neighbor = check['neighbor'] if kind == 'isis-adjacency' else str(ip_address(check['neighbor']))
                identities = {neighbor}
                if kind == 'isis-adjacency' and re.fullmatch(r'[0-9a-fA-F]{4}(?:\.[0-9a-fA-F]{4}){2}', neighbor):
                    neighbor = neighbor.lower()
                    identities = {neighbor}
                    if any(not re.fullmatch(r'[0-9a-fA-F]{4}(?:\.[0-9a-fA-F]{4}){2}', row['neighbor']) for row in rows):
                        evidence['hostname_command'] = 'show isis hostname'
                        mapping = parse_isis_hostnames(console.command('show isis hostname'))
                        aliases = {row['hostname'] for row in mapping if row['system_id'] == neighbor}
                        if any(row['hostname'] in aliases and row['system_id'] != neighbor for row in mapping):
                            raise RuntimeError('Ambiguous IS-IS hostname mapping')
                        identities.update(aliases)
                        evidence['hostname_mapping'] = [row for row in mapping if row['system_id'] == neighbor]
                    rows = [{**row, 'neighbor': row['neighbor'].lower()}
                            if re.fullmatch(r'[0-9a-fA-F]{4}(?:\.[0-9a-fA-F]{4}){2}', row['neighbor']) else row
                            for row in rows]
                matches = [row for row in rows if row['neighbor'] in identities
                           or (kind == 'ospf-neighbor' and row['address'] == neighbor)]
                # Absence never implies Down; every matching adjacency must agree.
                passed = bool(matches) and all(row['state'] == check['state'].lower() for row in matches)
                evidence.update(neighbor=neighbor, observed=matches)
        if not passed:
            evidence['reason'] = 'Observed result does not match acceptance criteria'
        return passed, evidence
    except RuntimeError as error:
        evidence['reason'] = str(error)
        return False, evidence


def _evaluate_l2(console, c):
    try:
        if c["type"] == "iosxe-vlan":
            text = _clean(console.command("show vlan id " + str(c["vlan"])))
            if not re.search(r"VLAN\s+Name\s+Status", text): raise RuntimeError("Unrecognized VLAN table")
            active = bool(re.search(r"^\s*"+str(c["vlan"])+r"\s+\S+\s+active\b", text, re.M))
            return active, {"vlan": c["vlan"], "active": active}
        text = _clean(console.command("show interfaces " + c["interface"] + " switchport"))
        admin = re.search(r"Administrative Mode: (.+)", text)
        op = re.search(r"Operational Mode: (.+)", text)
        field = "Trunking VLANs Enabled" if c["mode"] == "trunk" else "Access Mode VLAN"
        found = re.search(field+r": ([0-9,-]+)",text)
        if not admin or not op or not found: raise RuntimeError("Incomplete switchport response")
        vlans=set()
        for item in found[1].split(','):
            ends=list(map(int,item.split('-')))
            if len(ends)>2 or not 1<=ends[0]<=ends[-1]<=4094: raise RuntimeError("Invalid switchport VLAN range")
            vlans.update(range(ends[0],ends[-1]+1))
        mode = "static access" if c["mode"] == "access" else "trunk"
        passed=admin[1].strip()==mode and op[1].strip() in (mode,c["mode"]) and vlans==set(c["vlans"])
        return passed,{"administrative_mode":admin[1].strip(),"operational_mode":op[1].strip(),"vlans":sorted(vlans)}
    except RuntimeError as error:
        return False,{"reason":str(error),"failed_layer":"vlan-l2"}
