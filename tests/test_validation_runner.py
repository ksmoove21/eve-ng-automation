"""Offline runner/CLI regression tests; all API and SSH access is mocked."""
from contextlib import ExitStack
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

import yaml

from eve_lab.cli import main
from eve_lab.device_console import (
    Console, _clean_console_output, _read_only_nudge_diagnostic,
)
from eve_lab.deploy import named as discover_nodes
from eve_lab.validation import _checks, _open_console, validate_lab

ROOT = Path(__file__).resolve().parents[1]


class RunnerTests(unittest.TestCase):
    def run_checks(self, checks, outputs=None, open_error=None, interfaces=None):
        topology = {'name': 'fixture', 'nodes': [{'name': 'edge'}, {'name': 'core'}], 'validation': checks}
        nodes = {name: {'template': 'c8000v', 'status': '2', 'name': name} for name in ('edge', 'core')}
        console = MagicMock()
        console.command.side_effect = outputs
        console.interface_status.return_value = [{'interface': 'Gi1', 'ip_address': '192.0.2.1',
                                                  'status': 'up', 'protocol': 'up'}]
        if interfaces is not None:
            console.interface_status.side_effect = interfaces
        channel = MagicMock()
        with ExitStack() as stack:
            named = stack.enter_context(patch('eve_lab.validation.named', wraps=discover_nodes))
            stack.enter_context(patch('eve_lab.validation.load_server', return_value={
                'url': 'https://example.invalid', 'ssh_username': 'test', 'ssh_password': 'test'}))
            stack.enter_context(patch('eve_lab.validation.credentials', return_value=['test'] * 3))
            ssh = stack.enter_context(patch('eve_lab.validation.paramiko.SSHClient')).return_value
            opened = stack.enter_context(patch('eve_lab.validation._open_console', return_value=(channel, console)))
            if open_error:
                opened.side_effect = open_error
            client = MagicMock()
            client.request.return_value = {str(i): node for i, node in enumerate(nodes.values())}
            before = deepcopy(topology)
            report = validate_lab(client, topology, ROOT)
            self.assertEqual(topology, before)
            client.request.assert_called_once_with('GET', 'labs/fixture.unl/nodes')
            named.assert_called_once()
            ssh.load_system_host_keys.assert_called_once()
            ssh.connect.assert_called_once()
            ssh.set_missing_host_key_policy.assert_not_called()
            ssh.close.assert_called_once()
        return report, opened, console, channel

    def test_grouping_reuses_one_console_per_node_and_preserves_required_failure(self):
        checks = [
            {'name': 'edge-route', 'node': 'edge', 'type': 'default-route', 'expected': 'present'},
            {'name': 'core-route', 'node': 'core', 'type': 'default-route', 'expected': 'absent'},
            {'name': 'edge-interface', 'node': 'edge', 'type': 'interface', 'interface': 'Gi1'},
        ]
        report, opened, console, channel = self.run_checks(checks, ['', '% Network not in table', '', '% Network not in table'])
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(channel.close.call_count, 2)
        self.assertEqual(report['result'], 'fail')
        self.assertEqual([c['name'] for c in report['checks']], ['edge-route', 'edge-interface', 'core-route'])
        self.assertEqual([c['result'] for c in report['checks']], ['fail', 'pass', 'pass'])
        self.assertTrue(all(isinstance(c['evidence'], dict) for c in report['checks']))
        self.assertEqual([c.args[0] for c in console.command.call_args_list], [
            'terminal length 0', 'show ip route 0.0.0.0 0.0.0.0',
            'terminal length 0', 'show ip route 0.0.0.0 0.0.0.0'])

    def test_explicit_optional_failure_remains_visible(self):
        checks = [{'name': 'route', 'node': 'edge', 'type': 'default-route', 'expected': 'present', 'required': False}]
        report, _, _, _ = self.run_checks(checks, ['', '% Network not in table'])
        self.assertEqual(report['result'], 'pass')
        self.assertEqual(report['checks'][0]['result'], 'fail')
        self.assertFalse(report['checks'][0]['required'])

    def test_console_login_failure_gives_evidence_for_every_check(self):
        checks = [{'name': str(i), 'node': 'edge', 'type': 'default-route', 'expected': 'present'} for i in range(2)]
        report, opened, _, _ = self.run_checks(checks, open_error=RuntimeError('Read-only login refused setup'))
        opened.assert_called_once()
        self.assertEqual(report['result'], 'fail')
        self.assertEqual(len(report['checks']), 2)
        self.assertTrue(all(c['result'] == 'fail' for c in report['checks']))

    def test_unsupported_platform_and_invalid_intent_fail_before_ssh(self):
        intent = {'name': 'route', 'node': 'edge', 'type': 'default-route', 'expected': 'present'}
        topology = {'name': 'fixture', 'nodes': [{'name': 'edge'}], 'validation': [intent]}
        with patch('eve_lab.validation.named', return_value={'edge': {'template': 'other', 'status': '2'}}), \
                patch('eve_lab.validation.paramiko.SSHClient') as ssh:
            with self.assertRaisesRegex(ValueError, 'IOS-family'):
                validate_lab(MagicMock(), topology, ROOT)
            ssh.assert_not_called()
        topology['validation'][0]['vrf'] = 'BLUE\nreload'
        with patch('eve_lab.validation.named') as named:
            with self.assertRaises(ValueError):
                validate_lab(MagicMock(), topology, ROOT)
            named.assert_not_called()

    def test_baseline_definition_and_legacy_report_shape(self):
        topology = yaml.safe_load((ROOT / 'labs/iosxe-baseline/topology.yaml').read_text())
        checks = _checks(topology)
        self.assertEqual([c['type'] for c in checks], ['interface', 'interface', 'ping', 'ping'])
        checks = [{**c, 'node': 'edge' if c['node'] == 'R1' else 'core'} for c in checks]
        interfaces = [[{'interface': 'Gi1', 'ip_address': address, 'status': 'up', 'protocol': 'up'}]
                      for address in ('10.255.0.1', '10.255.0.2')]
        report, opened, _, _ = self.run_checks(checks, ['Success rate is 100 percent (5/5)'] * 2,
                                               interfaces=interfaces)
        self.assertEqual(report['result'], 'pass')
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(set(report), {'lab', 'result', 'checks'})
        self.assertTrue(all(set(c) == {'name', 'type', 'node', 'result', 'evidence'} for c in report['checks']))


class ReadOnlyLoginTests(unittest.TestCase):
    def console(self, responses, boot_timeout=60):
        channel = MagicMock()
        encoded = [response.encode() for response in responses]
        channel.recv_ready.side_effect = lambda: channel.recv.call_count < len(encoded)
        channel.recv.side_effect = encoded
        channel.closed = False
        channel.exit_status_ready.return_value = False
        return Console(channel, boot_timeout=boot_timeout), channel

    def fallback_console(self, before_return=None, prompt='R1#'):
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        chunks = ([before_return.encode()] if before_return is not None else []) + [prompt.encode()]

        def ready():
            if before_return is not None and channel.recv.call_count == 0:
                return True
            prompt_index = 1 if before_return is not None else 0
            return channel.sendall.call_count >= 2 and channel.recv.call_count == prompt_index

        channel.recv_ready.side_effect = ready
        channel.recv.side_effect = chunks
        return Console(channel, boot_timeout=.01), channel

    def test_privileged_prompt_from_ctrl_r_needs_no_return(self):
        console, channel = self.console(['R1#'])
        console.login('user', 'pass', 'secret', read_only=True)
        self.assertEqual(console.prompt, 'R1#')
        self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12'])

    def test_silent_console_gets_one_return_then_privileged_prompt(self):
        console, channel = self.fallback_console()
        console.login('user', 'pass', 'secret', read_only=True)
        self.assertEqual(console.prompt, 'R1#')
        self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12', '\r'])

    def test_syslog_then_silence_gets_one_return_then_prompt(self):
        console, channel = self.fallback_console(
            '*Sep 27 12:00:00.000: %LINEPROTO-5-UPDOWN: Line protocol changed state to up\n')
        console.login('user', 'pass', 'secret', read_only=True)
        self.assertEqual(console.prompt, 'R1#')
        self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12', '\r'])

    def test_realistic_telnet_noise_permits_one_return_fallback(self):
        preamble = (
            'Trying 127.0.0.1...\n'
            'Connected to 127.0.0.1.\n'
            "Escape character is '^]'.\n"
        )
        cases = (
            preamble,
            preamble + '*Sep 27 12:00:00.000: %LINEPROTO-5-UPDOWN: Interface is up\n',
            preamble + 'R1#^R',
            preamble + '^R',
            preamble + '\x12',
            preamble + '%SYS-5-CONFIG_I: Configured from console\nR1#^R',
        )
        for buffered in cases:
            console, channel = self.fallback_console(buffered)
            with self.subTest(buffered=repr(buffered)):
                console.login('user', 'pass', 'secret', read_only=True)
                self.assertEqual(console.prompt, 'R1#')
                self.assertEqual(
                    [call.args[0] for call in channel.sendall.call_args_list],
                    ['\x12', '\r'])

    def test_complete_osc_title_sequences_are_removed(self):
        self.assertEqual(_clean_console_output('\x1b]0;R1\x07'), '')
        self.assertEqual(_clean_console_output('\x1b]2;R3\x1b\\'), '')

    def test_osc_title_with_telnet_preamble_permits_one_return(self):
        buffered = (
            'Trying 127.0.0.1...\n'
            'Connected to 127.0.0.1.\n'
            "Escape character is '^]'.\n"
            '\x1b]0;R1\x07'
        )
        console, channel = self.fallback_console(buffered)
        console.login('user', 'pass', 'secret', read_only=True)
        self.assertEqual(console.prompt, 'R1#')
        self.assertEqual(
            [call.args[0] for call in channel.sendall.call_args_list],
            ['\x12', '\r'])

    def test_incomplete_and_unknown_escape_sequences_refuse(self):
        sequences = (
            '\x1b]0;R1',
            '\x1bPtitle\x07',
            '\x1b]9;R1\x07',
        )
        for sequence in sequences:
            console, channel = self.console([sequence], boot_timeout=.01)
            with self.subTest(sequence=repr(sequence)), self.assertRaisesRegex(
                    RuntimeError, 'Read-only'):
                console.login('user', 'pass', 'secret', read_only=True)
            channel.sendall.assert_called_once_with('\x12')

    def test_osc_normalization_preserves_printable_text_outside_sequence(self):
        output = _clean_console_output(
            'before\x1b]1;printable title payload\x07after')
        self.assertEqual(output, 'beforeafter')

    def test_read_only_recovers_running_ios_prompt_with_syslog_and_redisplay(self):
        for hostname, redisplay in (('R1', '^R'), ('R3', '\x12')):
            response = (
                '*Sep 27 12:00:00.000: %LINEPROTO-5-UPDOWN: Line protocol changed state to up\n'
                f'{hostname}#{redisplay}{hostname}#'
                '*Sep 27 12:00:01.000: %SYS-5-CONFIG_I: Configured from console\n'
            )
            console, channel = self.console([response, f'terminal length 0\n{hostname}#'])
            with self.subTest(hostname=hostname):
                console.login('user', 'pass', 'secret', read_only=True)
                self.assertEqual(console.prompt, hostname + '#')
                console.command('terminal length 0')
                self.assertEqual([call.args[0] for call in channel.sendall.call_args_list],
                                 ['\x12', 'terminal length 0\r'])

    def test_setup_prompts_refuse_without_return_fallback(self):
        prompts = (
            'Enter enable secret:', 'Confirm enable secret:', 'Enter your selection [2]:',
            'Would you like to enter the initial configuration dialog? [yes/no]:',
            'Press RETURN to get started!', 'Are you sure? [yes/no]:',
        )
        for prompt in prompts:
            console, channel = self.console([prompt], boot_timeout=.01)
            with self.subTest(prompt=prompt), self.assertRaisesRegex(RuntimeError, 'Read-only'):
                console.login('user', 'pass', 'secret', read_only=True)
            self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12'])

    def test_username_and_password_prompts_refuse_without_return_fallback(self):
        for prompt in ('Username:', 'Password:'):
            console, channel = self.console([prompt])
            with self.subTest(prompt=prompt), self.assertRaisesRegex(RuntimeError, 'Read-only'):
                console.login('user', 'pass', 'secret', read_only=True)
            self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12'])

    def test_configuration_mode_prompt_refuses(self):
        for prompt in ('R1(config)#', 'R1(config-if)#'):
            console, channel = self.console([prompt])
            with self.subTest(prompt=prompt), self.assertRaisesRegex(RuntimeError, 'Read-only'):
                console.login('user', 'pass', 'secret', read_only=True)
            self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12'])

    def test_refusal_diagnostic_reports_structure_without_console_text(self):
        buffered = (
            '\n'
            'Trying 127.0.0.1...\n'
            'Connected to 127.0.0.1.\n'
            "Escape character is '^]'.\n"
            '^R\n'
            '*Sep 27 12:00:00.000: %SYS-5-CONFIG_I: changed\n'
            'R1#\n'
            'Username:\n'
            'R1(config)#\n'
            'private printable text\x07'
        )
        evidence = _read_only_nudge_diagnostic(buffered)
        for expected in (
                'lines=10', 'blank=1', 'telnet=3', 'ctrl_r=1', 'syslog=1',
                'exec=1', 'unsafe_interactive=1', 'config_prompt=1',
                'unclassified=1', 'unclassified_lengths=[23]',
                'unclassified_has_controls=[true]', 'control_codes=[["U+0007"]]'):
            self.assertIn(expected, evidence)
        for private in ('127.0.0.1', 'R1', 'Username', 'private', 'printable', 'changed'):
            self.assertNotIn(private, evidence)

    def test_refusal_error_never_exposes_unclassified_console_text(self):
        private = 'R1#show secret 192.0.2.1 admin\x07'
        console, channel = self.console([private], boot_timeout=.01)
        with self.assertRaises(RuntimeError) as raised:
            console.login('private-user', 'private-password', 'private-secret', read_only=True)
        message = str(raised.exception)
        self.assertIn('classification:', message)
        self.assertIn(f'unclassified_lengths=[{len(private)}]', message)
        self.assertIn('unclassified_has_controls=[true]', message)
        self.assertIn('control_codes=[["U+0007"]]', message)
        for private_text in (private[:-1], '192.0.2.1', 'admin', 'private-user',
                             'private-password', 'private-secret'):
            self.assertNotIn(private_text, message)
        channel.sendall.assert_called_once_with('\x12')

    def test_pending_input_refuses_without_return(self):
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        channel.recv_ready.side_effect = [True, False]
        channel.recv.return_value = b'router#reload'
        console = Console(channel, boot_timeout=.01)
        with self.assertRaisesRegex(RuntimeError, 'Read-only'):
            console.login('user', 'pass', 'secret', read_only=True)
        channel.sendall.assert_called_once_with('\x12')

    def test_fallback_return_happens_at_most_once(self):
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        channel.recv_ready.return_value = False
        console = Console(channel, boot_timeout=.01)
        with patch('eve_lab.device_console.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                console.login('user', 'pass', 'secret', read_only=True)
        self.assertEqual([call.args[0] for call in channel.sendall.call_args_list], ['\x12', '\r'])

    def test_enable_cannot_enter_configuration_mode(self):
        console, channel = self.console(['router>', 'router(config)#'])
        with self.assertRaisesRegex(RuntimeError, 'Read-only'):
            console.login('user', 'pass', 'secret', read_only=True)
        self.assertNotIn('end\r', [call.args[0] for call in channel.sendall.call_args_list])

    def test_open_console_uses_read_only_login_and_closes_failed_channel(self):
        ssh = MagicMock()
        node = {'console': 'telnet', 'url': 'telnet://example.invalid:32769'}
        channel = ssh.get_transport.return_value.open_session.return_value
        with patch('eve_lab.validation.Console') as factory:
            _open_console(ssh, node, ['user', 'pass', 'secret'], 60)
            factory.return_value.login.assert_called_once_with('user', 'pass', 'secret', read_only=True)
            channel.exec_command.assert_called_once_with('telnet 127.0.0.1 32769')
            factory.return_value.login.side_effect = RuntimeError('setup refused')
            with self.assertRaises(RuntimeError):
                _open_console(ssh, node, ['user', 'pass', 'secret'], 60)
            channel.close.assert_called_once()


class CliTests(unittest.TestCase):
    def test_validate_exit_code_tracks_report_and_logs_out(self):
        for result in ('pass', 'fail'):
            with self.subTest(result=result), ExitStack() as stack:
                stack.enter_context(patch('sys.argv', ['eve', 'validate', 'fixture']))
                stack.enter_context(patch('eve_lab.cli.load_server', return_value={
                    'url': 'https://example.invalid', 'username': 'test', 'password': 'test'}))
                stack.enter_context(patch('eve_lab.cli.load_topology', return_value={'name': 'fixture'}))
                client = stack.enter_context(patch('eve_lab.cli.EveClient')).return_value
                stack.enter_context(patch('eve_lab.cli.validate_lab', return_value={'result': result, 'checks': []}))
                stdout = stack.enter_context(patch('sys.stdout', new_callable=StringIO))
                if result == 'fail':
                    with self.assertRaises(SystemExit) as error:
                        main()
                    self.assertEqual(error.exception.code, 1)
                else:
                    self.assertIsNone(main())
                self.assertEqual(json.loads(stdout.getvalue())['result'], result)
                client.login.assert_called_once_with('test', 'test', html5=False)
                client.logout.assert_called_once()


if __name__ == '__main__':
    unittest.main()
