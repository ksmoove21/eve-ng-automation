import unittest
from unittest.mock import MagicMock
from eve_lab.validation import _checks
from eve_lab.validation_nxos import evaluate

def check(kind, **values):
    return {'name': 'x', 'node': 'n', 'type': kind, **values}

class NxosTests(unittest.TestCase):
    def test_interface_names_and_line_endings(self):
        for interface in ('Ethernet1/1', 'Ethernet1/49'):
            for ending in ('\n', '\r\n', '\n\n\n'):
                console = MagicMock()
                console.command.return_value = interface + ' is up' + ending + 'admin state is up' + ending
                intent = check('nxos-interface', interface=interface, admin_state='up', oper_state='up')
                with self.subTest(interface=interface, ending=repr(ending)):
                    self.assertEqual(_checks({'validation': [intent]}), [intent])
                    self.assertTrue(evaluate(console, intent)[0])
    def test_port_channel_members_accept_slashes(self):
        console = MagicMock()
        console.command.side_effect = ['Po10 is up\r\n', '10 Po10(SU) LACP Ethernet1/1(P) Ethernet1/49(P)\r\n']
        intent = check('nxos-port-channel', port_channel='Po10', members=['Ethernet1/1', 'Ethernet1/49'])
        self.assertTrue(evaluate(console, intent)[0])
    def test_negative_and_malformed_fail_closed(self):
        console = MagicMock(); console.command.return_value = 'Ethernet1/1 is up\nadmin state is bad\n'
        self.assertFalse(evaluate(console, check('nxos-interface', interface='Ethernet1/1', oper_state='up'))[0])
        console = MagicMock(); console.command.return_value = '% Route not found\n'
        self.assertTrue(evaluate(console, check('nxos-route', prefix='192.0.2.0/24', expected='absent'))[0])
        self.assertFalse(evaluate(console, check('nxos-route', prefix='192.0.2.0/24', expected='present'))[0])
    def test_invalid_intent_is_rejected(self):
        for intent in (check('nxos-ping', destination='192.0.2.2', vrf='BLUE\nreload'), check('nxos-interface', interface='Ethernet1/1;reload')):
            with self.assertRaises(ValueError): _checks({'validation': [intent]})
if __name__ == '__main__':
    unittest.main()
