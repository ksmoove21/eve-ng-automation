import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock
from eve_lab.initialize_nxos import NxosConsole, bootstrap_commands, load_bootstrap

DATA={'hostname':'leaf1','management_interface':'mgmt0','management_address':'192.0.2.10','management_prefix_length':24,'management_gateway':'192.0.2.1','boot_image':'nxos-image.bin'}
class NxosInitTests(unittest.TestCase):
 def test_baseline_commands_and_save(self):
  commands=bootstrap_commands(DATA)
  self.assertEqual(commands,['hostname leaf1','interface mgmt0','ip address 192.0.2.10/24','no cdp enable','exit','boot nxos bootflash:nxos-image.bin','vrf context management','ip route 0.0.0.0/0 192.0.2.1','exit'])
  console=MagicMock(spec=NxosConsole); console.command.side_effect=['']*12
  NxosConsole.initialize(console,commands)
  self.assertEqual([call.args[0] for call in console.command.call_args_list][0],'configure terminal')
  self.assertEqual(console.command.call_args_list[-1].args[0],'copy running-config startup-config')
 def test_missing_or_malformed_intent_fails(self):
  for data in ({}, {**DATA,'management_prefix_length':0}, {**DATA,'management_interface':'mgmt0;reload'}, {**DATA,'extra':'x'}):
   with self.subTest(data=data):
    with self.assertRaises(ValueError): bootstrap_commands(data)
 def test_yaml_and_save_failure(self):
  with TemporaryDirectory() as temp:
   path=Path(temp)/'node-init.yaml'; path.write_text('hostname: leaf1\nmanagement_interface: mgmt0\nmanagement_address: 192.0.2.10\nmanagement_prefix_length: 24\nmanagement_gateway: 192.0.2.1\nboot_image: nxos-image.bin\n')
   self.assertEqual(load_bootstrap(path),bootstrap_commands(DATA))
  console=MagicMock(spec=NxosConsole); console.command.side_effect=['']*11+['% Error']
  with self.assertRaises(RuntimeError): NxosConsole.initialize(console,bootstrap_commands(DATA))
if __name__=='__main__': unittest.main()
