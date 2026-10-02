"""Synthetic offline IOS XE fixtures: these are not live verification."""
from copy import deepcopy
import unittest
from unittest.mock import MagicMock, patch

from eve_lab.validation import _checks
from eve_lab.validation_iosxe import (
    evaluate, parse_route, parse_bgp, parse_ospf, parse_isis,
    parse_isis_hostnames, parse_ping,
)

ROUTE = '''Routing entry for 192.0.2.0/24
  Known via "ospf 1", distance 110, metric 2, type intra area
  Routing Descriptor Blocks:
  * 198.51.100.1, from 203.0.113.1, 00:01:00 ago, via GigabitEthernet1
      Route metric is 2, traffic share count is 1
    198.51.100.2, from 203.0.113.2, 00:01:00 ago, via GigabitEthernet2
      Route metric is 2, traffic share count is 1
'''
BGP_HEADER = 'Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n'
BGP = BGP_HEADER + '192.0.2.2 4 65002 20 30 3 0 0 00:01:02 0\n'
OSPF_HEADER = 'Neighbor ID Pri State Dead Time Address Interface\n'
OSPF = OSPF_HEADER + '203.0.113.2 1 FULL/DR 00:00:32 192.0.2.2 Gi1\n'
ISIS_HEADER = 'System Id Type Interface IP Address State Holdtime Circuit Id\n'
ISIS = ISIS_HEADER + '0000.0000.0002 L2 Gi1 192.0.2.2 UP 24 peer.01\n'
HOSTS = 'Level System ID Dynamic Hostname (CORE)\n 2 0000.0000.0002 peer\n * 0000.0000.0001 local\n'
PING = 'Success rate is 100 percent (5/5), round-trip min/avg/max = 1/2/3 ms\n'


def check(kind, **values):
    return {'name': 'acceptance', 'node': 'router', 'type': kind, **values}


CASES = [
    (check('route', prefix='192.0.2.0/24', expected='present', next_hop='198.51.100.2'),
     ROUTE, 'show ip route 192.0.2.0 255.255.255.0'),
    (check('default-route', expected='present', vrf='BLUE'),
     ROUTE.replace('192.0.2.0/24', '0.0.0.0/0, supernet'), 'show ip route vrf BLUE 0.0.0.0 0.0.0.0'),
    (check('bgp-neighbor', neighbor='192.0.2.2', state='Established'), BGP,
     'show bgp ipv4 unicast summary'),
    (check('ospf-neighbor', neighbor='203.0.113.2', state='FULL'), OSPF, 'show ip ospf neighbor'),
    (check('isis-adjacency', neighbor='0000.0000.0002', state='UP'), ISIS, 'show isis neighbors'),
    (check('vrf-ping', vrf='BLUE', destination='192.0.2.2', min_success_rate=100), PING,
     'ping vrf BLUE 192.0.2.2 repeat 5 timeout 2'),
    (check('mtu-ping', destination='192.0.2.2', packet_size=1500, df=True, min_success_rate=100), PING,
     'ping 192.0.2.2 repeat 5 timeout 2 size 1500 df-bit'),
]


class SchemaTests(unittest.TestCase):
    def test_all_primitives_preserve_intent(self):
        for intent, _, _ in CASES:
            with self.subTest(kind=intent['type']):
                before = deepcopy(intent)
                self.assertEqual(_checks({'validation': [intent]}), [before])
                self.assertEqual(intent, before)

    def test_rejects_invalid_fields_types_and_injection(self):
        invalid = [
            check('route', prefix='192.0.2.1/24', expected='present'),
            check('route', prefix='::/0', expected='present'),
            check('route', prefix='192.0.2.0/255.255.255.0', expected='present'),
            check('route', prefix='192.0.2.0/24', expected='absent', next_hop='192.0.2.1'),
            check('route', prefix='192.0.2.0/24', expected='present', next_hop=1),
            check('default-route', expected='anything'),
            check('default-route', expected='absent', vrf='BLUE\nreload'),
            check('default-route', expected='absent', vrf='BLUE | include x'),
            check('bgp-neighbor', neighbor='192.0.2.2', state='full'),
            check('bgp-neighbor', neighbor='192.0.2.2', state='idle', address_family='vpnv4'),
            check('bgp-neighbor', neighbor='2001:db8::2', state='idle'),
            check('ospf-neighbor', neighbor='bad', state='full'),
            check('isis-adjacency', neighbor='peer', state='established'),
            check('isis-adjacency', neighbor='peer;reload', state='up'),
            check('vrf-ping', destination='192.0.2.2'),
            check('vrf-ping', vrf='BLUE', destination='192.0.2.2\nreload'),
            check('vrf-ping', vrf='BLUE', destination='192.0.2.2', min_success_rate=True),
            check('mtu-ping', destination='192.0.2.2', packet_size=True, df=True),
            check('mtu-ping', destination='192.0.2.2', packet_size=35, df=True),
            check('mtu-ping', destination='192.0.2.2', packet_size=18025, df=True),
            check('mtu-ping', destination='192.0.2.2', packet_size=1500, df='false'),
            check('mtu-ping', destination='192.0.2.2', packet_size=1500, df=True, required='yes'),
            check('default-route', expected='present', command='reload'),
            check([], expected='present'),
        ]
        for intent in invalid:
            with self.subTest(intent=intent), self.assertRaises(ValueError):
                _checks({'validation': [intent]})

    def test_required_fields_cannot_be_omitted(self):
        required = [('prefix', 'expected'), ('expected',), ('neighbor', 'state'),
                    ('neighbor', 'state'), ('neighbor', 'state'), ('vrf', 'destination'),
                    ('destination', 'packet_size', 'df')]
        for (intent, _, _), fields in zip(CASES, required):
            for field in fields:
                incomplete = {k: v for k, v in intent.items() if k != field}
                with self.subTest(kind=intent['type'], field=field), self.assertRaises(ValueError):
                    _checks({'validation': [incomplete]})


class ParserTests(unittest.TestCase):
    def test_route_ecmp_and_directly_connected(self):
        self.assertEqual(parse_route(ROUTE), {'prefix': '192.0.2.0/24', 'present': True,
                                            'next_hops': ['198.51.100.1', '198.51.100.2']})
        direct = '''Routing entry for 192.0.2.0/24
 Known via "connected", distance 0, metric 0
 Routing Descriptor Blocks:
 * directly connected, via GigabitEthernet1
   Route metric is 0, traffic share count is 1
'''
        self.assertEqual(parse_route(direct)['next_hops'], [])
        self.assertTrue(parse_route('Routing Table: BLUE\n' + ROUTE)['present'])

    def test_route_explicit_absence(self):
        for response in ('% Network not in table', '% Subnet not in table',
                         'Routing Table: BLUE\n% Network not in table\n'):
            self.assertFalse(parse_route(response)['present'])

    def test_route_does_not_confuse_error_with_absence(self):
        for response in ('', '% IP routing not enabled', '% VRF BLUE does not exist',
                         ROUTE.split('Routing Descriptor Blocks:')[0],
                         ROUTE.replace('Route metric is 2,', ''), ROUTE + ROUTE,
                         ROUTE.replace('198.51.100.1', '999.51.100.1')):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                parse_route(response)

    def test_bgp_established_zero_prefixes_and_idle(self):
        rows = parse_bgp(BGP + '192.0.2.3 4 65003 0 0 1 0 0 never Idle(Admin)\n')
        self.assertEqual(rows[0]['state'], 'established')
        self.assertEqual(rows[0]['prefixes_received'], 0)
        self.assertEqual(rows[1]['state'], 'idle')
        self.assertEqual(parse_bgp(BGP_HEADER), [])

    def test_bgp_asdot_and_spaced_admin_state(self):
        row = parse_bgp(BGP_HEADER + '192.0.2.2 4 1.2 0 0 1 0 0 never Idle (Admin)\n')[0]
        self.assertEqual(row['state'], 'idle')
        self.assertEqual(row['reported_state'], 'Idle (Admin)')

    def test_bgp_wrapped_ipv6(self):
        rows = parse_bgp(BGP_HEADER + '2001:db8:1234:5678::2\n 4 65002 20 30 3 0 0 00:01:02 7\n')
        self.assertEqual(rows[0]['neighbor'], '2001:db8:1234:5678::2')
        self.assertEqual(rows[0]['prefixes_received'], 7)

    def test_ospf_states_and_neighbor_identity(self):
        rows = parse_ospf(OSPF + '203.0.113.3 0 2WAY/DROTHER 00:00:31 192.0.2.3 Gi2\n')
        self.assertEqual(rows[0]['neighbor'], '203.0.113.2')
        self.assertEqual(rows[1]['state'], '2way')
        self.assertEqual(parse_ospf(OSPF_HEADER), [])

    def test_ospf_point_to_point_role_spacing(self):
        self.assertEqual(parse_ospf(OSPF.replace('FULL/DR', 'FULL/  -'))[0]['state'], 'full')

    def test_isis_levels_and_addressless_adjacency(self):
        rows = parse_isis(ISIS + 'peer L1L2 Gi2 UP 20 peer.02\n')
        self.assertEqual(rows[0]['level'], 'L2')
        self.assertIsNone(rows[1]['address'])
        self.assertEqual(parse_isis(ISIS_HEADER), [])

    def test_isis_hostname_mapping(self):
        self.assertEqual(parse_isis_hostnames(HOSTS)[0],
                         {'system_id': '0000.0000.0002', 'hostname': 'peer'})
        with self.assertRaises(RuntimeError):
            parse_isis_hostnames(HOSTS + '2 bad peer\n')

    def test_ping_counters_and_consistency(self):
        self.assertEqual(parse_ping(PING), {'success_rate': 100, 'received': 5, 'sent': 5})
        for response in ('Success rate is 100 percent (4/5)', 'Success rate is 100 percent (0/0)',
                         'Success rate is 100 percent (10/10)', 'Success rate is 120 percent (6/5)',
                         PING + PING, '.....'):
            with self.subTest(response=response), self.assertRaises(RuntimeError):
                parse_ping(response)

    def test_all_parsers_reject_unknown_truncated_or_error_output(self):
        for parser, output in ((parse_route, ROUTE), (parse_bgp, BGP), (parse_ospf, OSPF),
                               (parse_isis, ISIS), (parse_isis_hostnames, HOSTS), (parse_ping, PING)):
            for bad in ('', 'garbage', '% Invalid input', output + '\n--More--', output + '\n% Error'):
                with self.subTest(parser=parser.__name__, bad=bad), self.assertRaises(RuntimeError):
                    parser(bad)
        for parser, header in ((parse_bgp, BGP_HEADER), (parse_ospf, OSPF_HEADER), (parse_isis, ISIS_HEADER)):
            with self.subTest(parser=parser.__name__), self.assertRaises(RuntimeError):
                parser(header + '192.0.2.2\n')


class PrimitiveTests(unittest.TestCase):
    def test_every_primitive_passes_with_structured_evidence_and_exact_command(self):
        for intent, output, command in CASES:
            with self.subTest(kind=intent['type']):
                console = MagicMock()
                console.command.return_value = output
                before = deepcopy(intent)
                passed, evidence = evaluate(console, intent)
                self.assertTrue(passed, evidence)
                self.assertEqual(evidence['command'], command)
                self.assertEqual(console.command.call_args.args[0], command)
                self.assertIn('expected', evidence)
                self.assertEqual(intent, before)

    def test_every_primitive_fails_with_evidence_on_command_error_or_bad_output(self):
        for intent, _, _ in CASES:
            for error in (False, True):
                with self.subTest(kind=intent['type'], error=error):
                    console = MagicMock()
                    console.command.return_value = 'unexpected output'
                    if error:
                        console.command.side_effect = RuntimeError('Cisco rejected a command')
                    passed, evidence = evaluate(console, intent)
                    self.assertFalse(passed)
                    self.assertIn('reason', evidence)
                    self.assertIn('expected', evidence)
                    self.assertIn('command', evidence)

    def test_route_presence_absence_exact_prefix_and_next_hop(self):
        cases = [(ROUTE, 'present', True), (ROUTE, 'absent', False),
                 ('% Network not in table', 'present', False), ('% Network not in table', 'absent', True),
                 (ROUTE.replace('192.0.2.0/24', '192.0.0.0/16'), 'present', False),
                 (ROUTE.replace('192.0.2.0/24', '192.0.0.0/16'), 'absent', True),
                 ('% VRF BLUE does not exist', 'absent', False)]
        for output, expected, passes in cases:
            console = MagicMock()
            console.command.return_value = output
            with self.subTest(output=output, expected=expected):
                self.assertEqual(evaluate(console, check('route', prefix='192.0.2.0/24', expected=expected))[0], passes)
        console.command.return_value = ROUTE
        self.assertFalse(evaluate(console, check('route', prefix='192.0.2.0/24', expected='present', next_hop='198.51.100.9'))[0])

    def test_default_route_requires_exact_default(self):
        console = MagicMock()
        for output, expected, passes in ((ROUTE, 'present', False), ('% Network not in table', 'absent', True),
                                        (ROUTE.replace('192.0.2.0/24', '0.0.0.0/0'), 'absent', False)):
            console.command.return_value = output
            self.assertEqual(evaluate(console, check('default-route', expected=expected))[0], passes)

    def test_bgp_scoped_commands(self):
        for family, vrf, neighbor, scope in (
            ('ipv4-unicast', 'BLUE', '192.0.2.2', 'vpnv4 unicast vrf BLUE'),
            ('ipv6-unicast', None, '2001:db8::2', 'ipv6 unicast'),
            ('ipv6-unicast', 'BLUE', '2001:db8::2', 'vpnv6 unicast vrf BLUE'),
        ):
            console = MagicMock()
            console.command.return_value = BGP.replace('192.0.2.2', neighbor)
            intent = check('bgp-neighbor', neighbor=neighbor, state='established', address_family=family)
            if vrf:
                intent['vrf'] = vrf
            passed, evidence = evaluate(console, intent)
            self.assertTrue(passed, evidence)
            self.assertEqual(evidence['command'], 'show bgp ' + scope + ' summary')

    def test_adjacency_missing_and_wrong_state_fail(self):
        for intent, output, _ in CASES[2:5]:
            for response in (output.splitlines()[0] + '\n', output.replace('00:01:02 0', 'never Active').replace('FULL/DR', 'INIT/DROTHER').replace(' UP ', ' DOWN ')):
                console = MagicMock()
                console.command.return_value = response
                with self.subTest(kind=intent['type'], response=response):
                    self.assertFalse(evaluate(console, intent)[0])

    def test_ospf_accepts_neighbor_address_and_all_matching_rows_must_agree(self):
        console = MagicMock()
        console.command.return_value = OSPF
        intent = check('ospf-neighbor', neighbor='192.0.2.2', state='full')
        self.assertTrue(evaluate(console, intent)[0])
        console.command.return_value += '203.0.113.2 1 INIT/DR 00:00:32 192.0.2.2 Gi2\n'
        self.assertFalse(evaluate(console, intent)[0])

    def test_isis_system_id_resolves_dynamic_hostname(self):
        console = MagicMock()
        console.command.side_effect = [ISIS.replace('0000.0000.0002', 'peer'), HOSTS]
        passed, evidence = evaluate(console, CASES[4][0])
        self.assertTrue(passed, evidence)
        self.assertEqual(evidence['hostname_mapping'][0]['hostname'], 'peer')
        self.assertEqual(console.command.call_args.args, ('show isis hostname',))
        console.command.side_effect = [ISIS.replace('0000.0000.0002', 'peer'), HOSTS + '1 0000.0000.0003 peer\n']
        self.assertFalse(evaluate(console, CASES[4][0])[0])

    @patch("eve_lab.reachability.time.sleep")
    def test_new_pings_retry_bounded_and_keep_threshold(self, sleep):
        for intent, _, _ in CASES[5:]:
            console = MagicMock()
            console.command.side_effect = ['Success rate is 80 percent (4/5)', PING]
            passed, evidence = evaluate(console, intent)
            self.assertTrue(passed)
            self.assertEqual(len(evidence['attempts']), 2)
            self.assertEqual(evidence['minimum_success_rate'], 100)
            console.command.side_effect = ['Success rate is 0 percent (0/5)'] * 3
            self.assertFalse(evaluate(console, intent)[0])
            console.command.side_effect = None
            console.command.return_value = 'Success rate is 80 percent (4/5)'
            self.assertTrue(evaluate(console, {**intent, 'min_success_rate': 80})[0])

    def test_zero_threshold_cannot_pass_unparseable_ping(self):
        for intent, _, _ in CASES[5:]:
            console = MagicMock()
            console.command.return_value = 'Unknown host'
            passed, evidence = evaluate(console, {**intent, 'min_success_rate': 0})
            self.assertFalse(passed)
            self.assertIn('reason', evidence)

    def test_mtu_df_false_and_vrf_route(self):
        console = MagicMock()
        console.command.return_value = PING
        intent = {**CASES[6][0], 'df': False}
        self.assertTrue(evaluate(console, intent)[0])
        self.assertEqual(console.command.call_args.args[0], 'ping 192.0.2.2 repeat 5 timeout 2 size 1500')
        console.command.return_value = ROUTE
        self.assertTrue(evaluate(console, {**CASES[0][0], 'vrf': 'BLUE'})[0])
        self.assertEqual(console.command.call_args.args[0], 'show ip route vrf BLUE 192.0.2.0 255.255.255.0')


class TransparentBridgeTests(unittest.TestCase):
    def check(self):
        return {
            "name": "transport-fabric",
            "node": "internet",
            "type": "iosxe-transparent-bridge",
            "bridge_domain": 91,
            "service_instance": 1,
            "interfaces": [
                "Ethernet0/0", "Ethernet0/1",
                "Ethernet0/2", "Ethernet0/3",
            ],
        }

    def responses(self):
        running = "".join(
            "interface Ethernet0/" + str(number) + "\n"
            " no ip address\n"
            " service instance 1 ethernet\n"
            "  encapsulation untagged\n"
            "  bridge-domain 91\n"
            "!\n"
            for number in range(4)
        )
        summary = "\n".join(
            "Associated interface: Ethernet0/" + str(number)
            for number in range(4)
        )
        return running, summary, "Bridge-domain 91 state: UP\n"

    def test_schema_and_exact_operational_membership_pass(self):
        check = self.check()
        self.assertEqual(_checks({"validation": [check]}), [check])
        console = MagicMock()
        console.command.side_effect = self.responses()
        passed, evidence = evaluate(console, check)
        self.assertTrue(passed, evidence)
        self.assertTrue(evidence["domain_present"])
        self.assertEqual(set(evidence["interfaces"]), set(check["interfaces"]))

    def test_missing_member_or_domain_fails(self):
        console = MagicMock()
        running, summary, domain = self.responses()
        console.command.side_effect = [
            running,
            summary.replace("Associated interface: Ethernet0/3", ""),
            domain,
        ]
        passed, evidence = evaluate(console, self.check())
        self.assertFalse(passed)
        self.assertFalse(
            evidence["interfaces"]["Ethernet0/3"]["operational_entry"])

    def test_schema_rejects_duplicate_interfaces_and_invalid_domain(self):
        duplicate = self.check()
        duplicate["interfaces"][1] = duplicate["interfaces"][0]
        invalid = self.check()
        invalid["bridge_domain"] = 0
        for check in (duplicate, invalid):
            with self.subTest(check=check), self.assertRaises(ValueError):
                _checks({"validation": [check]})


class SwitchportSchemaTests(unittest.TestCase):
    def test_accepts_iosv_and_modular_gigabit_names(self):
        for interface in ("GigabitEthernet0/0", "GigabitEthernet1/0/12"):
            check = {
                "name": "access-port",
                "node": "switch",
                "type": "iosxe-switchport",
                "interface": interface,
                "mode": "access",
                "vlans": [10],
            }
            self.assertEqual(_checks({"validation": [check]}), [check])

    def test_rejects_switchport_command_injection(self):
        check = {
            "name": "access-port",
            "node": "switch",
            "type": "iosxe-switchport",
            "interface": "GigabitEthernet0/0\nreload",
            "mode": "access",
            "vlans": [10],
        }
        with self.assertRaises(ValueError):
            _checks({"validation": [check]})


if __name__ == '__main__':
    unittest.main()
