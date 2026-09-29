import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import yaml
from eve_lab import iosxe_kg, validation_kg, validation_iosxe
from eve_lab.validation import _checks

PROFILE = dict(profile="kg-ipsec", hostname="KG-A", ct=dict(interface="GigabitEthernet1", address="192.0.2.1/30", peer="192.0.2.2"), pt=dict(interface="GigabitEthernet2", address="198.51.100.1/30"), tunnel=dict(interface="Tunnel10", address="203.0.113.1/30"), psk_env="LAB_PSK", routes=[])
CHECK = dict(name="boundary",node="KG-A",type="kg-boundary",ct_interface="GigabitEthernet1",ct_peer="192.0.2.2",ct_prefix="192.0.2.0/30",pt_interface="GigabitEthernet2",tunnel="Tunnel10",remote_prefixes=["198.51.100.8/30"],local_prefixes=["198.51.100.0/30"],pt_destination="198.51.100.9",pt_source="198.51.100.1")

class KgTests(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/"init.yaml";path.write_text(yaml.safe_dump(data))
            return iosxe_kg.load_profile(path)

    def test_profile_renders_ct_global_pt_red_and_passive_rip(self):
        data=self.load(PROFILE)
        with patch("eve_lab.iosxe_kg.environment_values",return_value={"LAB_PSK":"a"*32}):
            commands=iosxe_kg.render(data,Path("."))
        ct=commands[commands.index("interface GigabitEthernet1"):commands.index("interface GigabitEthernet2")]
        self.assertNotIn("vrf forwarding Red",ct)
        self.assertEqual(commands.count("vrf forwarding Red"),2)
        self.assertNotIn("tunnel vrf Red",commands)
        self.assertIn("match fvrf global",commands)
        self.assertIn("passive-interface default",commands)
        self.assertNotIn("passive-interface Tunnel10",commands)
        self.assertLess(commands.index("address-family ipv4 vrf Red"),commands.index("network 198.51.100.0"))

    def test_profile_rejects_overlap_invalid_peer_and_extra_fields(self):
        for mutate in (lambda d:d.update(role="kg"),lambda d:d["pt"].update(address="192.0.2.1/30"),lambda d:d["ct"].update(peer="192.0.2.1"),lambda d:d["ct"].update(interface="Gi1; reload"),lambda d:d.update(routes=[dict(prefix="192.0.2.0/30",next_hop="198.51.100.2")])):
            data=copy.deepcopy(PROFILE);mutate(data)
            with self.assertRaises(ValueError):self.load(data)

    def test_secret_is_required_and_not_in_error(self):
        for key in ("", "secret with newline\n", "x"):
            with patch("eve_lab.iosxe_kg.environment_values",return_value={"LAB_PSK":key}):
                with self.assertRaises(ValueError) as error:iosxe_kg.render(PROFILE,Path("."))
                self.assertNotIn("secret with newline",str(error.exception))

    def test_license_boot_transition_requires_save_and_observed_reload(self):
        c=MagicMock();c.command.side_effect=lambda command,**kw: 'License Level: \n' if command=='show version' else '[OK]'
        self.assertTrue(iosxe_kg.prepare_license(c))
        self.assertEqual(c.expect.call_count,2)
        self.assertEqual(c.pending,'')
        c=MagicMock();c.command.return_value='License Level: network-essentials\n'
        self.assertFalse(iosxe_kg.prepare_license(c))
        c.send.assert_not_called()
        c=MagicMock();c.command.side_effect=lambda command,**kw: 'License Level: \n' if command=='show version' else ''
        with self.assertRaisesRegex(RuntimeError,'save was not confirmed'):iosxe_kg.prepare_license(c)
        c.send.assert_not_called()

    def test_kg_acceptance_schema(self):
        self.assertEqual(_checks(dict(validation=[CHECK])),[CHECK])
        for key,value in (("remote_prefixes",[]),("ct_peer","bad"),("tunnel","Tunnel10\nreload")):
            c={**CHECK,key:value}
            with self.assertRaises(ValueError):_checks(dict(validation=[c]))

    def test_empty_response_fails_every_layer(self):
        console=MagicMock();console.command.return_value=""
        passed,evidence=validation_kg.evaluate(console,CHECK)
        self.assertFalse(passed)
        self.assertEqual(len(evidence["failed_layers"]),8)
        for call in console.command.call_args_list:
            self.assertTrue(call.args[0].startswith(("show ","ping ")))

    def test_l2_checks_require_operational_state(self):
        c=dict(type="iosxe-switchport",interface="GigabitEthernet1/0/1",mode="trunk",vlans=[10,20])
        console=MagicMock();console.command.return_value="Administrative Mode: trunk\nOperational Mode: trunk\nTrunking VLANs Enabled: 10,20\n"
        self.assertTrue(validation_iosxe.evaluate(console,c)[0])
        console.command.return_value=console.command.return_value.replace("Operational Mode: trunk","Operational Mode: down")
        self.assertFalse(validation_iosxe.evaluate(console,c)[0])



class KgEvidenceTests(unittest.TestCase):
    def responses(self):
        ping="Success rate is 100 percent (5/5)\n"
        route='Routing entry for 198.51.100.8/30\n Known via "rip", distance 120, metric 1\n Routing Descriptor Blocks:\n * 203.0.113.2, from 203.0.113.2\n Route metric is 1, traffic share count is 1\n'
        return {
            "ping 192.0.2.2 repeat 5 timeout 2":ping,
            "ping vrf Red 198.51.100.9 source 198.51.100.1 repeat 5 timeout 2":ping,
            "show ip vrf interfaces":"Interface IP-Address VRF Protocol\nGigabitEthernet2 198.51.100.1 Red up\nTunnel10 203.0.113.1 Red up\n",
            "show running-config interface GigabitEthernet1":"interface GigabitEthernet1\n ip address 192.0.2.1 255.255.255.252\n",
            "show interface Tunnel10":"Tunnel10 is up, line protocol is up\n",
            "show running-config interface Tunnel10":"interface Tunnel10\n vrf forwarding Red\n tunnel mode ipsec ipv4\n tunnel protection ipsec profile KG-IPSEC\n",
            "show crypto ikev2 sa":"Tunnel-id Local Remote fvrf/ivrf Status\n1 192.0.2.1/500 192.0.2.2/500 none/Red READY\n",
            "show crypto ipsec sa peer 192.0.2.2":"#pkts encaps: 5\n#pkts decaps: 5\ninbound esp sas:\n Status: ACTIVE\noutbound esp sas:\n Status: ACTIVE\n",
            "show running-config | section ^router rip":'router rip\n passive-interface default\n no passive-interface Tunnel10\n address-family ipv4 vrf Red\n  version 2\n  network 198.51.100.0\n  network 203.0.113.0\n exit-address-family\n',
            "show ip protocols vrf Red":'Routing Protocol is "rip"\n Tunnel10 2 2 No none\n',
            "show ip route vrf Red 198.51.100.8 255.255.255.252":route,
            "show ip route 198.51.100.0 255.255.255.252":"% Network not in table\n",
            "show ip route 198.51.100.8 255.255.255.252":"% Network not in table\n",
            "show ip route vrf Red 192.0.2.0 255.255.255.252":"% Network not in table\n",
        }

    def test_full_boundary_passes_with_operational_evidence(self):
        responses=self.responses();console=MagicMock()
        console.command.side_effect=lambda command,**kwargs:responses[command]
        passed,evidence=validation_kg.evaluate(console,CHECK)
        self.assertTrue(passed,evidence)
        self.assertEqual(evidence["failed_layers"],[])

    def test_layer_failures_cannot_be_hidden_by_other_passes(self):
        cases=[
            ("show crypto ikev2 sa","READY","NEGOTIATING","ike"),
            ("show crypto ipsec sa peer 192.0.2.2","#pkts decaps: 5","#pkts decaps: 0","ipsec"),
            ("show running-config interface Tunnel10","vrf forwarding Red","vrf forwarding Wrong","vti"),
            ("show ip route vrf Red 198.51.100.8 255.255.255.252",'Known via "rip"','Known via "static"',"rip"),
            ("show ip protocols vrf Red"," Tunnel10 2 2 No none"," GigabitEthernet1 2 2 No none","rip"),
            ("show running-config | section ^router rip","router rip","router rip\n network 192.0.2.0","rip"),
            ("show running-config interface GigabitEthernet1","interface GigabitEthernet1","interface GigabitEthernet1\n vrf forwarding Red","vrf-isolation-interfaces"),
        ]
        for command,old,new,layer in cases:
            with self.subTest(layer=layer):
                responses=self.responses();responses[command]=responses[command].replace(old,new)
                console=MagicMock();console.command.side_effect=lambda command,**kwargs:responses[command]
                passed,evidence=validation_kg.evaluate(console,CHECK)
                self.assertFalse(passed);self.assertIn(layer,evidence["failed_layers"])

    def test_plaintext_route_in_global_table_fails_isolation(self):
        responses=self.responses()
        responses["show ip route 198.51.100.8 255.255.255.252"]=responses["show ip route vrf Red 198.51.100.8 255.255.255.252"]
        console=MagicMock();console.command.side_effect=lambda command,**kwargs:responses[command]
        self.assertIn("vrf-isolation-routes",validation_kg.evaluate(console,CHECK)[1]["failed_layers"])
