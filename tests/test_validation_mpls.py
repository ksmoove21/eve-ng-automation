"""Synthetic MPLS fixtures; live qualification is recorded separately."""
import unittest
from unittest.mock import MagicMock
from eve_lab.validation import _checks
from eve_lab.validation_iosxe import command_for,evaluate as ios_evaluate
from eve_lab.validation_mpls import parse_ldp,parse_lfib,evaluate

LDP='''    Peer LDP Ident: 192.0.2.2:0; Local LDP Ident 192.0.2.1:0
        TCP connection: 192.0.2.2.646 - 192.0.2.1.49152
        State: Oper; Msgs sent/rcvd: 12/11; Downstream
        Up time: 00:00:20
        LDP discovery sources:
          GigabitEthernet0/0, Src IP addr: 198.51.100.2
'''
HEADER='Local Outgoing Prefix Bytes Label Outgoing Next Hop\nLabel Label or VC or Tunnel Id Switched interface\n'
LFIB=HEADER+'16 20 192.0.2.3/32 0 Gi0/0 198.51.100.2\n17 Pop Label 192.0.2.2/32 140 Gi0/0 198.51.100.2\n'
BGP='Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n192.0.2.2 4 64512 10 10 1 0 0 00:01:00 0\n'

def check(kind,**kw):return {'name':'proof','node':'router','type':kind,**kw}

class MplsTests(unittest.TestCase):
    def test_ldp_operational_and_label_space(self):
        self.assertEqual(parse_ldp(LDP)[0]['state'],'operational')
        c=MagicMock();c.command.return_value=LDP
        self.assertTrue(evaluate(c,check('ldp-neighbor',neighbor='192.0.2.2',state='operational'))[0])
        c.command.return_value=LDP.replace('192.0.2.2:0','192.0.2.2:3')
        self.assertFalse(evaluate(c,check('ldp-neighbor',neighbor='192.0.2.2',state='operational'))[0])
        c.command.return_value=LDP.replace('192.0.2.1:0','192.0.2.1:3')
        self.assertFalse(evaluate(c,check('ldp-neighbor',neighbor='192.0.2.2',state='operational'))[0])
    def test_ldp_wrong_peer_or_truncated_response_fails(self):
        c=MagicMock();c.command.return_value=LDP
        self.assertFalse(evaluate(c,check('ldp-neighbor',neighbor='192.0.2.3',state='operational'))[0])
        for value in (LDP.split('Up time:')[0],LDP.replace('Oper','OpenRec'),'--More--', '% Invalid input'):
            c.command.return_value=value
            self.assertFalse(evaluate(c,check('ldp-neighbor',neighbor='192.0.2.2',state='operational'))[0])
    def test_lfib_label_swap_pop_and_exact_prefix(self):
        self.assertEqual([r['action'] for r in parse_lfib(LFIB)],['swap','pop'])
        c=MagicMock();c.command.return_value=LFIB
        self.assertTrue(evaluate(c,check('mpls-forwarding',prefix='192.0.2.3/32',expected='present',action='swap',next_hop='198.51.100.2'))[0])
        self.assertTrue(evaluate(c,check('mpls-forwarding',prefix='192.0.2.2/32',expected='present',action='pop'))[0])
        self.assertFalse(evaluate(c,check('mpls-forwarding',prefix='192.0.2.0/24',expected='present'))[0])
    def test_iosv_header_and_multiple_complete_ldp_blocks(self):
        header='Local      Outgoing   Prefix           Bytes Label   Outgoing   Next Hop\nLabel      Label      or Tunnel Id     Switched      interface\n'
        self.assertEqual(parse_lfib(LFIB.replace(HEADER,header))[0]['action'],'swap')
        second=LDP.replace('192.0.2.2','192.0.2.3')
        output=LDP+'        Addresses bound to peer LDP Ident:\n          198.51.100.2 192.0.2.2\n'+second
        self.assertEqual([r['neighbor'] for r in parse_ldp(output)],['192.0.2.2','192.0.2.3'])
    def test_unlabeled_and_wrong_next_hop_do_not_prove_forwarding(self):
        c=MagicMock();c.command.return_value=LFIB.replace('16 20','16 No Label')
        self.assertFalse(evaluate(c,check('mpls-forwarding',prefix='192.0.2.3/32',expected='present'))[0])
        c.command.return_value=LFIB
        self.assertFalse(evaluate(c,check('mpls-forwarding',prefix='192.0.2.3/32',expected='present',next_hop='198.51.100.9'))[0])
    def test_corrupt_lfib_fails_closed(self):
        for value in ('',LFIB+'18 3 broken\n',LFIB.replace('16 20','16 1048576'),LFIB.replace('192.0.2.3/32','192.0.2.3/24')):
            with self.assertRaises(RuntimeError):parse_lfib(value)
    def test_schema_rejects_injection_and_incompatible_families(self):
        invalid=[check('ldp-neighbor',neighbor='192.0.2.2;reload',state='operational'),check('ldp-neighbor',neighbor='192.0.2.2',state='down'),check('mpls-forwarding',prefix='192.0.2.1/24',expected='present'),check('mpls-forwarding',prefix='192.0.2.0/24',expected='absent',action='swap'),check('bgp-neighbor',neighbor='2001:db8::1',state='established',address_family='vpnv4')]
        for value in invalid:
            with self.assertRaises(ValueError):_checks({'validation':[value]})
    def test_vpnv4_zero_prefixes_still_established_and_vrf_scope(self):
        value=check('bgp-neighbor',neighbor='192.0.2.2',state='established',address_family='vpnv4')
        self.assertEqual(_checks({'validation':[value]}),[value])
        self.assertEqual(command_for(value),'show ip bgp vpnv4 all summary')
        c=MagicMock();c.command.return_value=BGP
        self.assertTrue(ios_evaluate(c,value)[0])
        self.assertEqual(command_for({**value,'vrf':'BLUE'}),'show ip bgp vpnv4 vrf BLUE summary')
    def test_ios_dispatches_mpls_and_empty_lfib_table(self):
        value=check('mpls-forwarding',prefix='192.0.2.3/32',expected='absent')
        self.assertEqual(_checks({'validation':[value]}),[value])
        c=MagicMock();c.command.return_value=HEADER
        self.assertTrue(ios_evaluate(c,value)[0])
        c.command.assert_called_once_with('show mpls forwarding-table', require_echo=True)
