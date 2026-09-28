import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from eve_lab.validation import _checks, validate_lab
from eve_lab.validation_nxos import evaluate
ROOT = Path(__file__).resolve().parents[1]
def check(kind, **values): return {'name':'x','node':'n','type':kind,**values}
I='Ethernet1/1 is up\nadmin state is up\nInternet Address is 192.0.2.1/24\n'
V='VLAN Name Status Ports\n10 USERS active Ethernet1/1\n'
R='192.0.2.0/24, ubest/mbest: 1/0\n *via 198.51.100.1, Ethernet1/1\n'
P='Success rate is 100.00% (5/5)\n'
VP='vPC status : Enabled\nPeer status : peer adjacency formed ok\nConfiguration consistency status : success\n1 Po1 up 1-10\n'
B='Neighbor V AS MsgRcvd MsgSent TblVer InQ OutQ Up/Down State/PfxRcd\n192.0.2.2 4 65002 1 1 1 0 0 00:01 5\n'
class NxosTests(unittest.TestCase):
 def test_primitives_positive_and_negative(self):
  cases=[(check('nxos-interface',interface='Ethernet1/1',admin_state='up',oper_state='up'),[I]),(check('nxos-vlan',vlan=10,state='active'),[V]),(check('nxos-vrf',vrf='BLUE'),['Name ID State Reason\nBLUE 2 Up --\n']),(check('nxos-route',prefix='192.0.2.0/24',expected='present',next_hop='198.51.100.1'),[R]),(check('nxos-ping',destination='192.0.2.2'),[P]),(check('nxos-vpc',state='up',peer_state='up',peer_link_state='up',consistency='up'),[VP]),(check('nxos-port-channel',port_channel='Po1',members=['Ethernet1/1','Ethernet1/49']),['Po1 is up\n','1 Po1(SU) LACP Ethernet1/1(P) Ethernet1/49(P)\n']),(check('nxos-bgp-neighbor',neighbor='192.0.2.2',state='established'),[B])]
  for intent,output in cases:
   c=MagicMock(); c.command.side_effect=output
   with self.subTest(intent=intent): self.assertEqual(_checks({'validation':[intent]}),[intent]); self.assertTrue(evaluate(c,intent)[0])
  c=MagicMock(); c.command.return_value='% Route not found\n'
  self.assertTrue(evaluate(c,check('nxos-route',prefix='192.0.2.0/24',expected='absent'))[0]); self.assertFalse(evaluate(c,check('nxos-route',prefix='192.0.2.0/24',expected='present'))[0])
  c=MagicMock(); c.command.return_value='Success rate is 40.00% (2/5)\n'; self.assertFalse(evaluate(c,check('nxos-ping',destination='192.0.2.2',min_success_rate=100))[0])
  c=MagicMock(); c.command.return_value=B.replace(' 5\n',' Idle\n'); self.assertFalse(evaluate(c,check('nxos-bgp-neighbor',neighbor='192.0.2.2',state='established'))[0])
 def test_line_endings_and_malformed_fail_closed(self):
  for name in ('Ethernet1/1','Ethernet1/49'):
   for end in ('\n','\r\n','\n\n'):
    c=MagicMock(); c.command.return_value=name+' is up'+end+'admin state is up'+end
    self.assertTrue(evaluate(c,check('nxos-interface',interface=name,oper_state='up'))[0])
  for output in ('Ethernet1/1 is up\nadmin state is bad\n',VP.replace('Enabled','mystery')):
   c=MagicMock(); c.command.return_value=output
   self.assertFalse(evaluate(c,check('nxos-vpc',state='up') if 'vPC' in output else check('nxos-interface',interface='Ethernet1/1',oper_state='up'))[0])
 def test_platform_family_rejection(self):
  topology={'name':'x','nodes':[{'name':'n'}],'validation':[check('nxos-vlan',vlan=10)]}
  for template in ('c8000v','paloalto'):
   with patch('eve_lab.validation.named',return_value={'n':{'template':template,'status':'2'}}), self.assertRaises(ValueError): validate_lab(MagicMock(),topology,ROOT)
  topology['validation']=[check('route',prefix='192.0.2.0/24',expected='present')]
  with patch('eve_lab.validation.named',return_value={'n':{'template':'nxosv9k','status':'2'}}), self.assertRaises(ValueError): validate_lab(MagicMock(),topology,ROOT)
 def test_runner_execution_failure_overrides_optional(self):
  topology={'name':'x','nodes':[{'name':'n'}],'validation':[check('nxos-vlan',vlan=10,required=False)]}
  node={'template':'nxosv9k','status':'2','name':'n'}
  with patch('eve_lab.validation.named',return_value={'n':node}), patch('eve_lab.validation.load_server',return_value={'url':'https://x','ssh_username':'u','ssh_password':'p'}), patch('eve_lab.validation.credentials',return_value=['u','p','s']), patch('eve_lab.validation.paramiko.SSHClient'), patch('eve_lab.validation._open_console',side_effect=RuntimeError('login refused')):
   report=validate_lab(MagicMock(),topology,ROOT)
  self.assertEqual(report['result'],'fail'); self.assertEqual(report['checks'][0]['evidence']['failure_kind'],'execution')
if __name__=='__main__': unittest.main()
