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
from eve_lab.device_console import Console
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
            with self.assertRaisesRegex(ValueError, 'c8000v'):
                validate_lab(MagicMock(), topology, ROOT)
            ssh.assert_not_called()
        topology['validation'][0]['vrf'] = 'BLUE\nreload'
        with patch('eve_lab.validation.named') as named:
            with self.assertRaises(ValueError):
                validate_lab(MagicMock(), topology, ROOT)
            named.assert_not_called()

    def test_baseline_definition_and_legacy_report_shape(self):
        topology = yaml.safe_load((ROOT / 'labs/unsc-baseline/topology.yaml').read_text())
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
    def console(self, responses):
        channel = MagicMock()
        channel.recv_ready.return_value = True
        channel.recv.side_effect = [response.encode() for response in responses]
        return Console(channel), channel

    def test_existing_authentication_works_read_only(self):
        console, channel = self.console(['Username:', 'Password:', 'router>', 'Password:', 'router#'])
        console.login('user', 'pass', 'secret', read_only=True)
        self.assertEqual([c.args[0] for c in channel.sendall.call_args_list],
                         ['\x12', 'user\r', 'pass\r', 'enable\r', 'secret\r'])

    def test_read_only_refuses_setup_and_config_prompts(self):
        for prompt in ('Enter enable secret:', 'Confirm enable secret:', 'Enter your selection [2]:',
                       'Would you like to enter the initial configuration dialog? [yes/no]:',
                       'router(config)#', 'router(config-if)#'):
            console, channel = self.console([prompt])
            with self.subTest(prompt=prompt), self.assertRaisesRegex(RuntimeError, 'Read-only'):
                console.login('user', 'pass', 'secret', read_only=True)
            self.assertEqual([c.args[0] for c in channel.sendall.call_args_list], ['\x12'])

    def test_pending_input_times_out_without_enter_or_periodic_wakeup(self):
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        channel.recv_ready.side_effect = [True, False]
        channel.recv.return_value = b'router#reload'
        console = Console(channel)
        with patch('eve_lab.device_console.time.monotonic', side_effect=[0, 1, 2, 11, 12, 61]), \
                patch('eve_lab.device_console.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                console.login('user', 'pass', 'secret', read_only=True)
        channel.sendall.assert_called_once_with('\x12')

    def test_enable_cannot_enter_configuration_mode(self):
        console, channel = self.console(['router>', 'router(config)#'])
        with self.assertRaisesRegex(RuntimeError, 'Read-only'):
            console.login('user', 'pass', 'secret', read_only=True)
        self.assertNotIn('end\r', [c.args[0] for c in channel.sendall.call_args_list])

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
