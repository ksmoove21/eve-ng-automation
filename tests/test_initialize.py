import tempfile
from pathlib import Path
import unittest
import paramiko
from unittest.mock import MagicMock, patch

from eve_lab.initialize import initialize, PaloConsole, config_commands
from eve_lab.client import EveClient


class InitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / 'labs/test/configs'
        self.base.mkdir(parents=True)
        (self.base / 'R0-init.cfg').write_text('hostname R0\n')
        self.nodes = {'7': {'name': 'R0', 'template': 'c8000v', 'status': 2,
                            'console': 'telnet', 'url': 'telnet://10.0.4.4:32775'}}
        self.client = MagicMock()
        self.client.request.return_value = self.nodes

    def run_init(self, **kwargs):
        return initialize(self.client, {'name': 'test'}, self.root, 'default', **kwargs)

    @patch('eve_lab.initialize.paramiko.SSHClient')
    def test_check_discovers_port_without_ssh(self, ssh):
        result = self.run_init(check=True)
        self.assertEqual(result['planned'][0]['port'], 32775)
        ssh.assert_not_called()

    def test_ios_family_templates_reuse_the_cisco_console_path(self):
        for template in ('c8000v', 'csr1000v', 'csr1000vng', 'isrv', 'iol', 'vios', 'viosl2'):
            with self.subTest(template=template):
                self.nodes['7']['template'] = template
                result = self.run_init(check=True)
                self.assertEqual(result['planned'][0]['template'], template)
                self.assertEqual(result['planned'][0]['file'], str(self.base / 'R0-init.cfg'))

    @patch('eve_lab.initialize.load_topology', return_value={'name': 'test'})
    @patch('eve_lab.initialize.compile_sdwan')
    def test_compiled_sdwan_ios_operations_override_generated_config_files(
            self, compile_sdwan, load_topology):
        (self.root / 'labs/test/intent.yaml').write_text('control_plane: {}\n')
        (self.base / 'R0-init.cfg').unlink()
        self.nodes['7']['template'] = 'iol'
        compile_sdwan.return_value = {
            'node_operations': {
                'R0': {
                    'adapter': 'ios-transparent-bridge',
                    'commands': ['hostname R0', 'bridge-domain 101'],
                },
            },
        }
        result = self.run_init(check=True)
        self.assertEqual(result['skipped'], [])
        self.assertEqual(
            result['planned'][0]['file'],
            str(self.root / 'labs/test/intent.yaml'))
        load_topology.assert_called_once_with(self.root, 'test')
        compile_sdwan.assert_called_once()

    @patch('eve_lab.initialize.compile_sdwan')
    def test_non_sdwan_intent_does_not_block_nxos_init(self, compile_sdwan):
        (self.root / 'labs/test/intent.yaml').write_text('scope: {site: DC2}\n')
        (self.base / 'R0-init.cfg').unlink()
        (self.base / 'R0-init.yaml').write_text(
            'hostname: R0\nmanagement_interface: mgmt0\n'
            'management_address: 192.0.2.10\nmanagement_prefix_length: 24\n'
            'management_gateway: 192.0.2.1\nboot_image: nxos.bin\n')
        self.nodes['7']['template'] = 'nxosv9k'
        result = self.run_init(check=True)
        self.assertEqual(result['skipped'], [])
        self.assertEqual([row['node'] for row in result['planned']], ['R0'])
        compile_sdwan.assert_not_called()

    def test_native_iol_blank_console_uses_advertised_telnet_url(self):
        self.nodes['7'].update(template='iol', console='')
        result = self.run_init(check=True)
        self.assertEqual(result['planned'][0]['port'], 32775)
        self.assertEqual(result['skipped'], [])

    def test_missing_and_unsupported_skipped(self):
        self.nodes['8'] = {'name': 'Other', 'template': 'unsupported'}
        (self.base / 'R0-init.cfg').unlink()
        self.assertEqual(len(self.run_init(check=True)['skipped']), 2)

    def test_stopped_and_non_telnet_rejected(self):
        self.nodes['7']['status'] = 0
        with self.assertRaisesRegex(ValueError, 'Start R0'):
            self.run_init(check=True)
        self.nodes['7']['status'] = 2
        self.nodes['7']['url'] = 'vnc://10.0.4.4:5900'
        with self.assertRaisesRegex(ValueError, 'Telnet'):
            self.run_init(check=True)

    def test_vnc_console_is_skipped_without_blocking_router(self):
        self.nodes['8'] = {'name': 'PA', 'template': 'paloalto', 'console': 'vnc'}
        result = self.run_init(check=True)
        self.assertEqual(result['planned'][0]['node'], 'R0')
        self.assertIn('Telnet serial console', result['skipped'][0]['reason'])

    def test_login_can_explicitly_request_native_console_urls(self):
        client = EveClient('http://example.invalid')
        client.request = MagicMock()
        client.login('admin', 'test', html5=False)
        client.request.assert_called_once_with('POST', 'auth/login',
                                               {'username': 'admin', 'password': 'test', 'html5': '0'})
    @patch('eve_lab.initialize.Console')
    @patch('eve_lab.initialize.paramiko.SSHClient')
    @patch('eve_lab.initialize.credentials', return_value=['admin', 'testpass', 'testenable'])
    @patch('eve_lab.initialize.load_server', return_value={'url': 'http://10.0.4.4', 'ssh_username': 'root', 'ssh_password': 'test'})
    def test_execution_uses_api_port_and_credentials(self, server, creds, ssh, console):
        console.return_value.interface_status.return_value = [{'interface': 'GigabitEthernet8', 'ip_address': '172.16.1.20'}]
        result = self.run_init(timeout=900)
        channel = ssh.return_value.get_transport.return_value.open_session.return_value
        channel.exec_command.assert_called_once_with('telnet 127.0.0.1 32775')
        console.assert_called_once_with(channel, boot_timeout=900)
        console.return_value.initialize.assert_called_once_with(['hostname R0'], username='admin', password='testpass')
        self.assertEqual(result['completed'], ['R0'])
        self.assertEqual(result['interface_status']['R0'][0]['ip_address'], '172.16.1.20')
        channel.close.assert_called_once()
        console.return_value.interface_status.side_effect = RuntimeError('read failed')
        result = self.run_init()
        self.assertEqual(result['completed'], ['R0'])
        self.assertEqual(result['failed'], [])
        self.assertIn('saved successfully', result['warnings'][0]['reason'])

    def test_palo_accepts_only_config_commands(self):
        path = self.base / 'PA-init.cfg'
        path.write_text('set deviceconfig system hostname PA\ncommit\n')
        with self.assertRaises(ValueError): config_commands(path, 'paloalto')

    @patch('eve_lab.initialize.paramiko.SSHClient')
    @patch('eve_lab.initialize.credentials', return_value=['admin', 'testpass', 'testenable'])
    @patch('eve_lab.initialize.load_server', return_value={'url': 'http://10.0.4.4', 'ssh_username': 'root', 'ssh_password': 'test'})
    def test_ssh_failures_identify_cause_without_opening_console(self, server, creds, ssh):
        for error, message in [
            (paramiko.BadHostKeyException('10.0.4.4', MagicMock(), MagicMock()), 'key has changed'),
            (paramiko.AuthenticationException('failed'), 'authentication failed'),
            (paramiko.SSHException("Server not found in known_hosts"), 'not trusted yet'),
            (paramiko.SSHException('negotiation failed'), 'handshake failed'),
            (TimeoutError(), 'TCP port 22'),
        ]:
            with self.subTest(message=message):
                ssh.return_value.connect.side_effect = error
                with self.assertRaisesRegex(RuntimeError, message):
                    self.run_init()
                ssh.return_value.get_transport.assert_not_called()

    def test_palo_does_not_claim_failed_commit_success(self):
        c = PaloConsole(MagicMock(), boot_timeout=600)
        c.command = MagicMock(return_value='Commit job queued')
        with self.assertRaisesRegex(RuntimeError, 'commit not confirmed'):
            c.initialize(['set deviceconfig system hostname PA'])
        c.command = MagicMock(return_value='Configuration committed successfully')
        c.initialize(['set deviceconfig system hostname PA'])
        self.assertEqual(c.command.call_args.args, ('exit',))

    def test_palo_mandatory_password_change_is_explicit(self):
        c = PaloConsole(MagicMock(), boot_timeout=600)
        match = MagicMock()
        match.group.return_value = 'Enter new password :'
        c.expect = MagicMock(return_value=('', match))
        with self.assertRaisesRegex(RuntimeError, 'mandatory password change'):
            c.login('admin', 'test')

    @patch('eve_lab.initialize.resolve_satellite_target', return_value='172.30.130.3')
    @patch('eve_lab.initialize.Console')
    @patch('eve_lab.initialize.paramiko.SSHClient')
    @patch('eve_lab.initialize.credentials', return_value=['admin', 'testpass', 'testenable'])
    @patch('eve_lab.initialize.load_server', return_value={'url': 'http://10.0.4.4', 'ssh_username': 'root', 'ssh_password': 'test'})
    def test_satellite_console_is_reached_through_selected_member(
            self, server, creds, ssh, console, resolve_target):
        self.nodes['7']['sat'] = 3
        self.client.request.side_effect = [
            self.nodes,
            {'3': {'id': 3, 'name': 'eve-sat03', 'online': 1,
                   'pubkey': 'VTxVhflwGkuBOsZs2kfD51KwG+1i5lxHywHOvjcUWCY='}},
        ]

        result = self.run_init(timeout=900)

        channel = ssh.return_value.get_transport.return_value.open_session.return_value
        resolve_target.assert_called_once_with(
            ssh.return_value,
            {'id': 3, 'name': 'eve-sat03', 'online': 1,
             'pubkey': 'VTxVhflwGkuBOsZs2kfD51KwG+1i5lxHywHOvjcUWCY='})
        command = channel.exec_command.call_args.args[0]
        self.assertIn('ssh -o BatchMode=yes -o StrictHostKeyChecking=yes', command)
        self.assertIn('172.30.130.3', command)
        self.assertIn('telnet 127.0.0.1 32775', command)
        self.assertEqual(result['planned'][0]['satellite'], 'eve-sat03')
        self.assertEqual(result['completed'], ['R0'])
