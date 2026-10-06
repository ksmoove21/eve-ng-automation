import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from eve_lab.initialize_nxos import NxosConsole, bootstrap_commands, load_bootstrap


DATA = {
    'hostname': 'leaf1',
    'management_interface': 'mgmt0',
    'management_address': '192.0.2.10',
    'management_prefix_length': 24,
    'management_gateway': '192.0.2.1',
    'boot_image': 'nxos-image.bin',
}
STARTUP = ('hostname leaf1\n ip address 192.0.2.10/24\n'
           ' ip route 0.0.0.0/0 192.0.2.1\n')
BOOT_STARTUP = STARTUP + 'boot nxos bootflash:/nxos-image.bin\n'


class NxosInitTests(unittest.TestCase):
    def test_baseline_commands_and_save(self):
        commands = bootstrap_commands(DATA)
        self.assertEqual(commands, [
            'hostname leaf1', 'interface mgmt0', 'ip address 192.0.2.10/24',
            'no cdp enable', 'exit', 'boot nxos bootflash:nxos-image.bin',
            'vrf context management', 'ip route 0.0.0.0/0 192.0.2.1', 'exit',
        ])
        console = MagicMock(spec=NxosConsole)
        console.command.side_effect = ['', '', 'bootflash:///nxos-image.bin'] + [''] * 11 + [BOOT_STARTUP, BOOT_STARTUP]
        NxosConsole.initialize(console, commands)
        sent = [call.args[0] for call in console.command.call_args_list]
        self.assertEqual(sent[:4], ['terminal length 0', 'terminal width 511', 'show version', 'configure terminal'])
        self.assertNotIn('boot nxos bootflash:nxos-image.bin', sent)
        self.assertEqual(sent[-3:], ['copy running-config startup-config',
                                     'show startup-config',
                                     'show running-config'])
        self.assertTrue(all(call.kwargs.get('require_echo') is True
                            for call in console.command.call_args_list))

    def test_missing_boot_image_is_set_only_after_management_save(self):
        commands = bootstrap_commands(DATA)
        console = MagicMock(spec=NxosConsole)
        reads = iter((STARTUP, BOOT_STARTUP))
        running_reads = iter(('', 'boot nxos bootflash:/nxos-image.bin'))
        def respond(command, **kwargs):
            if command == 'show version':
                return 'bootflash:///nxos-image.bin'
            if command == 'show startup-config':
                return next(reads)
            if command == 'show running-config':
                return next(running_reads)
            return ''
        console.command.side_effect = respond
        NxosConsole.initialize(console, commands)
        sent = [call.args[0] for call in console.command.call_args_list]
        boot = 'boot nxos bootflash:nxos-image.bin'
        self.assertEqual(sent.count(boot), 1)
        self.assertLess(sent.index('copy running-config startup-config'), sent.index(boot))
        self.assertEqual(sent.count('copy running-config startup-config'), 2)
        boot_call = next(call for call in console.command.call_args_list
                         if call.args[0] == boot)
        self.assertEqual(boot_call.kwargs['timeout'], 120)
        self.assertTrue(boot_call.kwargs['require_echo'])

    def test_saved_boot_without_running_boot_is_reapplied(self):
        console = MagicMock(spec=NxosConsole)
        running_reads = iter(('', 'boot nxos bootflash:/nxos-image.bin'))
        def respond(command, **kwargs):
            if command == 'show version':
                return 'bootflash:///nxos-image.bin'
            if command == 'show startup-config':
                return BOOT_STARTUP
            if command == 'show running-config':
                return next(running_reads)
            return ''
        console.command.side_effect = respond
        NxosConsole.initialize(console, bootstrap_commands(DATA))
        sent = [call.args[0] for call in console.command.call_args_list]
        self.assertIn('boot nxos bootflash:nxos-image.bin', sent)

    def test_conflicting_saved_boot_image_never_overwritten(self):
        console = MagicMock(spec=NxosConsole)
        console.command.side_effect = lambda command, **kwargs: (
            'bootflash:///nxos-image.bin' if command == 'show version' else
            STARTUP + 'boot nxos bootflash:/other-image.bin\n'
            if command == 'show startup-config' else
            '' if command == 'show running-config' else '')
        with self.assertRaisesRegex(RuntimeError, 'conflicting boot image'):
            NxosConsole.initialize(console, bootstrap_commands(DATA))
        sent = [call.args[0] for call in console.command.call_args_list]
        self.assertIn('copy running-config startup-config', sent)
        self.assertNotIn('boot nxos bootflash:nxos-image.bin', sent)

    def test_boot_command_timeout_keeps_prior_management_save(self):
        console = MagicMock(spec=NxosConsole)
        def respond(command, **kwargs):
            if command == 'show version':
                return 'bootflash:///nxos-image.bin'
            if command == 'show startup-config':
                return STARTUP
            if command == 'show running-config':
                return ''
            if command == 'boot nxos bootflash:nxos-image.bin':
                raise RuntimeError('console timeout')
            return ''
        console.command.side_effect = respond
        with self.assertRaisesRegex(RuntimeError, 'management was saved'):
            NxosConsole.initialize(console, bootstrap_commands(DATA))
        sent = [call.args[0] for call in console.command.call_args_list]
        self.assertLess(sent.index('copy running-config startup-config'),
                        sent.index('boot nxos bootflash:nxos-image.bin'))
        self.assertEqual(sent.count('copy running-config startup-config'), 1)

    def test_running_image_mismatch_stops_before_configuration(self):
        console = MagicMock(spec=NxosConsole)
        console.command.side_effect = ['', '', 'bootflash:///wrong-image.bin']
        with self.assertRaisesRegex(RuntimeError, 'running image differs'):
            NxosConsole.initialize(console, bootstrap_commands(DATA))
        self.assertEqual([call.args[0] for call in console.command.call_args_list],
                         ['terminal length 0', 'terminal width 511', 'show version'])

    def test_explicit_lacp_prerequisite(self):
        self.assertEqual(bootstrap_commands({**DATA, 'enable_lacp': True})[-1], 'feature lacp')
        with self.assertRaises(ValueError):
            bootstrap_commands({**DATA, 'enable_lacp': 'true'})

    def test_missing_or_malformed_intent_fails(self):
        for data in ({}, {**DATA, 'management_prefix_length': 0},
                     {**DATA, 'management_interface': 'mgmt0;reload'},
                     {**DATA, 'extra': 'x'}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                bootstrap_commands(data)

    def test_yaml_and_save_failure(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / 'node-init.yaml'
            path.write_text('hostname: leaf1\nmanagement_interface: mgmt0\n'
                            'management_address: 192.0.2.10\n'
                            'management_prefix_length: 24\n'
                            'management_gateway: 192.0.2.1\nboot_image: nxos-image.bin\n')
            self.assertEqual(load_bootstrap(path), bootstrap_commands(DATA))
        console = MagicMock(spec=NxosConsole)
        console.command.side_effect = ['', '', 'bootflash:///nxos-image.bin'] + [''] * 10 + ['% Error']
        with self.assertRaises(RuntimeError):
            NxosConsole.initialize(console, bootstrap_commands(DATA))

    def test_missing_startup_route_fails_even_when_copy_prompt_returns(self):
        console = MagicMock(spec=NxosConsole)
        console.command.side_effect = ['', '', 'bootflash:///nxos-image.bin'] + [''] * 12 + [
            'hostname leaf1\n ip address 192.0.2.10/24\n']
        with self.assertRaisesRegex(RuntimeError, 'startup-config lacks'):
            NxosConsole.initialize(console, bootstrap_commands(DATA))


if __name__ == '__main__':
    unittest.main()