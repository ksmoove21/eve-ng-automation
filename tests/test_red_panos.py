import unittest
from unittest.mock import MagicMock
from eve_lab.validation_panos import evaluate_operational

class OperationalTests(unittest.TestCase):
    def test_readiness_requires_finished_successful_commit(self):
        for jobs,expected in [('12 Commit FIN OK',True),('',False),('12 Commit ACT PEND',False),('12 Commit FIN OK\n13 Commit FIN FAIL',False)]:
            c=MagicMock();c.command.side_effect=['yes',jobs]
            self.assertEqual(evaluate_operational(c,dict(type='panos-readiness'))[0],expected)
    def test_interface_requires_recognized_up_state(self):
        for text,expected in [('Runtime link speed/duplex/state: 10000/full/up',True),('Link status: down',False),('unknown',False)]:
            c=MagicMock();c.command.return_value=text
            self.assertEqual(evaluate_operational(c,dict(type='panos-operational-interface',interface='ethernet1/1'))[0],expected)

    def test_committed_aggregate_subinterface_address(self):
        from eve_lab.validation_panos import parse_running_config,evaluate
        xml = '<config><devices><entry name="localhost.localdomain"><network><interface><aggregate-ethernet><entry name="ae1"><layer3><units><entry name="ae1.10"><ip><entry name="192.0.2.1/24"/></ip></entry></units></layer3></entry></aggregate-ethernet></interface></network></entry></devices></config>'
        root=parse_running_config(xml)
        for address,expected in [('192.0.2.1/24',True),('192.0.2.2/24',False)]:
            self.assertEqual(evaluate(root,dict(type='panos-interface',interface='ae1.10',address=address))[0],expected)

    def test_read_only_serial_refuses_configuration_and_password_setup(self):
        import re
        from eve_lab.validation import PaloReadOnlyConsole
        for prompt in ('admin@fw#','Enter new password:'):
            c=PaloReadOnlyConsole(MagicMock())
            c.expect=MagicMock(return_value=(prompt,re.search(r'.+',prompt)))
            with self.assertRaisesRegex(RuntimeError,'refuses setup/configuration'):c.login('admin','secret')
            c.channel.sendall.assert_called_once_with('\x15\r')
