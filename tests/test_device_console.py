import unittest
from unittest.mock import MagicMock, patch
from eve_lab.device_console import Console


class ConsoleTests(unittest.TestCase):
    def console(self, responses):
        channel = MagicMock()
        channel.recv_ready.return_value = True
        channel.recv.side_effect = [r.encode() for r in responses]
        return Console(channel), channel

    def test_send_secret_is_single_line_and_has_no_diagnostic_output(self):
        c, ch = self.console([])
        with patch('sys.stderr') as stderr:
            c.send_secret('sensitive-value')
        ch.sendall.assert_called_once_with('sensitive-value\r')
        self.assertNotIn('sensitive-value', str(stderr.write.call_args_list))
        with self.assertRaisesRegex(ValueError, 'single line'):
            c.send_secret('bad\nvalue')

    def test_login_with_credentials_and_enable(self):
        c, ch = self.console(['Username:', 'Password:', 'R0>', 'Password:', 'R0#'])
        c.login('admin', 'loginpass', 'enablepass')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list],
                         ['\r', 'admin\r', 'loginpass\r', 'enable\r', 'enablepass\r'])

    def test_login_handles_first_boot_password_initialization_with_secret_sends(self):
        c, ch = self.console(['login:', 'Password:', 'Enter new password:',
                              'Confirm new password:', 'vManage#'])
        c.login('admin', 'admin', 'unused-enable', new_password='private-password')
        self.assertEqual(c.prompt, 'vManage#')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list], [
            '\r', 'admin\r', 'admin\r', 'private-password\r', 'private-password\r'])

    def test_login_handles_viptela_initial_password_after_positive_banner(self):
        c, ch = self.console(['vmanage login:', 'Password:',
            'Last login: today\nWelcome to Viptela CLI\n'
            'You must set an initial admin password different from default password.\nPassword:',
            'Re-enter password:', 'vManage#'])
        c.login('admin', 'admin', 'unused-enable', new_password='private-password')
        self.assertEqual(c.prompt, 'vManage#')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list], [
            '\r', 'admin\r', 'admin\r', 'private-password\r', 'private-password\r'])

    def test_vmanage_first_boot_selects_persona_largest_data_disk_and_relogs(self):
        c, ch = self.console([
            'vmanage login:', 'Password:',
            'Welcome to Viptela CLI\nYou must set an initial admin password.\nPassword:',
            'Re-enter password:',
            '1) COMPUTE_AND_DATA\n2) DATA\n3) COMPUTE\n'
            'Select persona for vManage (1, 2 or 3):',
            'You chose persona COMPUTE_AND_DATA (1)\nAre you sure? [y/n]',
            'Available storage devices:\nvdb 100GB\nhdc 3GB\n'
            '1) vdb\n2) hdc\nSelect storage device to use:',
            'Would you like to format vdb? (y/n):',
            'vManage#', 'vmanage login:', 'Password:', 'vManage#'])
        c.login('admin', 'admin', 'unused', new_password='private-password',
                vmanage_first_boot=True)
        self.assertEqual(c.prompt, 'vManage#')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list], [
            '\x12', 'admin\r', 'admin\r', 'private-password\r',
            'private-password\r', '1\r', 'y\r', '1\r', 'y\r',
            'admin\r', 'private-password\r'])

    def test_vmanage_first_boot_rejects_only_small_or_uncorrelated_storage(self):
        c, _ = self.console([
            'Available storage devices:\nhdc 3GB\n1) hdc\n'
            'Select storage device to use:'])
        with self.assertRaisesRegex(RuntimeError, 'eligible 100GB'):
            c.login('admin', 'admin', 'unused', new_password='private-password',
                    vmanage_first_boot=True)

    def test_vmanage_resume_accepts_prompt_redisplayed_by_ctrl_r_without_return(self):
        c, ch = self.console([
            '1) COMPUTE_AND_DATA\n2) DATA\n3) COMPUTE\n'
            'Select persona for vManage (1, 2 or 3):',
            'vManage#'])
        c.login('admin', 'private-password', 'unused',
                new_password='private-password', vmanage_first_boot=True)
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list],
                         ['\x12', '1\r'])

    def test_login_stops_after_one_repeated_password_prompt(self):
        c, ch = self.console(['login:', 'Password:', 'Password:'])
        with self.assertRaisesRegex(RuntimeError, 'repeated a password prompt after one'):
            c.login('admin', 'admin', 'unused-enable')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list],
                         ['\r', 'admin\r', 'admin\r'])

    def test_login_stops_after_one_repeated_login_prompt(self):
        c, ch = self.console(['login:', 'login:'])
        with self.assertRaisesRegex(RuntimeError, 'repeated login'):
            c.login('admin', 'admin', 'unused-enable')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list],
                         ['\r', 'admin\r'])

    def test_initial_password_setup_can_relogin_once_with_new_password(self):
        c, ch = self.console([
            'login:', 'Password:', 'Enter new password:',
            'Confirm new password:', 'login:', 'Password:', 'vSmart#'])
        c.login('admin', 'admin', 'unused-enable',
                new_password='private-password')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list], [
            '\r', 'admin\r', 'admin\r', 'private-password\r',
            'private-password\r', 'admin\r', 'private-password\r'])

    def test_login_exhaustion_reports_only_prompt_classes(self):
        c, _ = self.console(['Would you like to enter setup?'] * 20)
        with self.assertRaisesRegex(
                RuntimeError, r'prompt sequence: (other-interactive,){19}'):
            c.login('admin', 'secret-value', 'enable-value')

    def test_login_calls_correlation_hook_before_first_password(self):
        c, ch = self.console(['login:', 'Password:', 'Router#'])
        events = []
        def correlated():
            events.append(('correlated', ch.sendall.call_count))
        c.login('admin', 'loginpass', 'enable',
                on_password_submit=correlated)
        self.assertEqual(events, [('correlated', 2)])

    def test_initial_boot(self):
        c, ch = self.console(['Would you like to enter the initial configuration dialog? [yes/no]:',
                             'Press RETURN to get started!', 'Router>', 'Router#'])
        c.login('admin', 'pass', 'secret')
        self.assertEqual(c.prompt, 'Router#')

    def test_initial_enable_secret_confirmation_and_save(self):
        c, ch = self.console([
            'Would you like to enter the initial configuration dialog? [yes/no]:',
            'Enter enable secret:', 'Confirm enable secret:',
            'Enter your selection [2]:', 'Press RETURN to get started!',
            'Router>', 'Password:', 'Router#'])
        with patch('sys.stderr'):
            c.login('admin', 'loginpass', 'enablepass')
        self.assertEqual([v.args[0] for v in ch.sendall.call_args_list],
                         ['\r', 'no\r', 'enablepass\r', 'enablepass\r', '2\r',
                          '\r', 'enable\r', 'enablepass\r'])
        self.assertEqual(c.prompt, 'Router#')

    def test_initial_secret_rejection_does_not_loop_or_disclose_secret(self):
        c, ch = self.console(['Enter enable secret:', 'Enter enable secret:'])
        with patch('sys.stderr') as stderr:
            with self.assertRaisesRegex(RuntimeError, 'CISCO_ENABLE_SECRET') as error:
                c.login('admin', 'loginpass', 'sensitive-value')
        self.assertNotIn('sensitive-value', str(error.exception))
        self.assertNotIn('sensitive-value', str(stderr.write.call_args_list))
        self.assertEqual(ch.sendall.call_count, 2)

    def test_initial_secret_confirmation_stops_wakeup_enters(self):
        c = Console(MagicMock())
        import re
        c.expect = MagicMock(side_effect=[('', re.match('.*', text)) for text in
                            ['Enter enable secret:', 'Confirm enable secret:', 'Router#']])
        with patch('sys.stderr'):
            c.login('admin', 'loginpass', 'enablepass')
        self.assertEqual([call.kwargs['wake'] for call in c.expect.call_args_list], [True, False, False])

    def test_poap_answer_stops_wakeup_enters_during_admin_setup(self):
        import re
        c = Console(MagicMock())
        c.expect = MagicMock(side_effect=[('', re.match('.*', text)) for text in
                            ['Abort Power On Auto Provisioning (yes/no)[no]:',
                             'Do you want to enforce secure password standard (yes/no) [y]:',
                             'Enter the password for "admin":',
                             'Confirm the password for "admin":', 'switch#']])
        c.login('admin', 'test-password', 'enablepass')
        self.assertEqual([call.kwargs['wake'] for call in c.expect.call_args_list],
                         [True, False, False, False, False])
        self.assertEqual([call.args[0] for call in c.channel.sendall.call_args_list],
                         ['\r', 'yes\r', 'yes\r', 'test-password\r', 'test-password\r'])

    def test_viptela_admin_setup_uses_requested_new_password(self):
        import re
        c = Console(MagicMock())
        c.expect = MagicMock(side_effect=[('', re.match('.*', text)) for text in
                            ['Enter the password for "admin":',
                             'Confirm the password for "admin":', 'vBond#']])
        c.login('admin', 'factory-password', 'enablepass',
                new_password='configured-password')
        self.assertEqual(
            [call.args[0] for call in c.channel.sendall.call_args_list],
            ['\r', 'configured-password\r', 'configured-password\r'])

    def test_initial_wait_wakes_console_after_early_enter_is_lost(self):
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        channel.recv_ready.side_effect = lambda: channel.sendall.called
        channel.recv.return_value = b'Router#'
        c = Console(channel)
        with patch('eve_lab.device_console.time.monotonic', side_effect=[0, 1, 11, 12, 13]), \
                patch('eve_lab.device_console.time.sleep'):
            c.expect(r'Router#', wake=True)
        channel.sendall.assert_called_once_with('\r')

    def test_terminal_controls_and_buffered_prompts(self):
        c, ch = self.console(['\x1b[32mUsername:\x1b[0m\nPassword:'])
        self.assertEqual(c.expect(r'Username:')[1].group(), 'Username:')
        self.assertEqual(c.expect(r'Password:')[1].group(), 'Password:')
        ch.recv.assert_called_once()

    def test_password_wait_does_not_send_extra_enter(self):
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        channel.recv_ready.return_value = False
        c = Console(channel)
        with patch('eve_lab.device_console.time.monotonic', side_effect=[0, 1, 11, 61]), \
                patch('eve_lab.device_console.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Timed out'):
                c.expect(r'Password:')
        channel.sendall.assert_not_called()

    def interrupted_console(self, response, redraw=True):
        import itertools
        channel = MagicMock()
        channel.closed = False
        channel.exit_status_ready.return_value = False
        pending = [response.encode()]
        channel.recv_ready.side_effect = lambda: bool(pending)
        channel.recv.side_effect = lambda size: pending.pop(0)
        def send(value):
            if value == '\x12' and redraw:
                pending.append(b'\r\n\x12R0(config-if)#')
        channel.sendall.side_effect = send
        return Console(channel), channel, itertools.count().__next__

    def test_command_redisplays_prompt_interrupted_by_async_output(self):
        for message in ('Guestshell destroyed successfully',
                        '01: %SYS-5-RESTART: System restarted --',
                        ' 2026 Sep 29 switch %$ VDC-1 %$ interface event'):
            c, ch, clock = self.interrupted_console(
                'no shutdown\r\nR0(config-if)#' + message + '\r\n')
            with patch('eve_lab.device_console.time.monotonic', side_effect=clock), \
                    patch('eve_lab.device_console.time.sleep'):
                output = c.command('no shutdown')
            self.assertIn(message, output)
            sent = [x.args[0] for x in ch.sendall.call_args_list]
            self.assertEqual(sent[0], 'no shutdown\r')
            self.assertGreaterEqual(sent.count('\x12'), 1)
            self.assertLessEqual(sent.count('\x12'), 10)

    def test_redisplay_keeps_command_errors_and_is_bounded(self):
        for response, redraw, error in (
                ('bad command\n% Invalid input\nR0#Startup message\n', True, 'rejected'),
                ('no shutdown\nR0#Startup message\n', False, 'Timed out')):
            c, ch, clock = self.interrupted_console(response, redraw)
            with patch('eve_lab.device_console.time.monotonic', side_effect=clock), \
                    patch('eve_lab.device_console.time.sleep'), patch('sys.stderr'):
                with self.assertRaisesRegex(RuntimeError, error):
                    c.command('no shutdown', timeout=8)
            sent = [x.args[0] for x in ch.sendall.call_args_list]
            self.assertEqual(sent[0], 'no shutdown\r')
            self.assertGreaterEqual(sent.count('\x12'), 1)
            self.assertLessEqual(sent.count('\x12'), 10)

    def test_command_consumes_buffered_prompt_redraw_before_next_response(self):
        c, ch = self.console([
            'write memory\nBuilding configuration...\n[OK]\nR0#\n'
            '%SYS-5-CONFIG_I: Configured from console\nR0#',
            'show version\nTechnology Package License Information:\n'
            'network-essentials Smart License network-essentials\nR0#'])
        self.assertIn('[OK]', c.command('write memory'))
        output = c.command('show version')
        self.assertIn('Technology Package License Information:', output)
        self.assertEqual(c.pending, '')
        self.assertEqual(ch.recv.call_count, 2)

    def test_echo_correlation_ignores_delayed_previous_prompt(self):
        c, ch = self.console([
            'R0(config)#',  # Delayed redraw from the previous command.
            'ip domain name example.com\nR0(config)#',
        ])
        c.pending = 'R0(config)#'
        c.command('ip domain name example.com', require_echo=True)
        self.assertEqual(ch.recv.call_count, 2)
        ch.sendall.assert_called_once_with('ip domain name example.com\r')
        self.assertEqual(c.prompt, 'R0(config)#')

    def test_echo_correlation_keeps_rejection_detection(self):
        c, _ = self.console([
            'ip domain name example.com\n% Invalid input\nR0(config)#',
        ])
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            c.command('ip domain name example.com', require_echo=True)

    def test_init_can_require_each_command_echo(self):
        c = Console(MagicMock())
        c.command = MagicMock(return_value='[OK]\n')
        c.initialize(['ip domain name example.com'], require_echo=True)
        self.assertTrue(all(call.kwargs.get('require_echo') is True
                            for call in c.command.call_args_list))

    def test_backup_strips_echo_and_checks_complete(self):
        c, _ = self.console(['terminal length 0\nR0#',
                            'more system:running-config\nUsing 99 out of 999 bytes\nhostname R0\n!\nend\nR0#'])
        self.assertEqual(c.backup(), 'hostname R0\n!\nend\n')
        c, _ = self.console(['R0#', 'hostname R0\nR0#'])
        with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
            c.backup()

    def test_interface_status_reads_all_addresses_without_dhcp_changes(self):
        c = Console(MagicMock())
        c.command = MagicMock(side_effect=['',
            'Interface IP-Address OK? Method Status Protocol\n'
            'GigabitEthernet1 172.16.1.20 YES DHCP up up\n'
            'GigabitEthernet2 unassigned YES unset administratively down down\n'
            'Loopback0 10.1.1.1 YES manual up up\n'])
        result = c.interface_status()
        self.assertEqual(result[0]['ip_address'], '172.16.1.20')
        self.assertEqual(result[0]['method'], 'DHCP')
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]['ip_address'], '10.1.1.1')
        self.assertEqual([call.args[0] for call in c.command.call_args_list],
                         ['terminal length 0', 'show ip interface brief'])
        c.command = MagicMock(return_value='Interface IP-Address OK? Method Status Protocol\n'
                             'GigabitEthernet2 unassigned YES unset administratively down down\n')
        self.assertEqual(c.interface_status(), [])

    def test_interface_status_rejects_unrecognized_response(self):
        c = Console(MagicMock())
        c.command = MagicMock(return_value='Unexpected output')
        with self.assertRaisesRegex(RuntimeError, 'Unrecognized'):
            c.interface_status()

    def test_init_stops_on_rejected_command_without_saving(self):
        c, ch = self.console(['R0(config)#', '% Invalid input detected at marker\nR0(config)#'])
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            c.initialize(['bad command'])
        self.assertFalse(any('write memory' in v.args[0] for v in ch.sendall.call_args_list))

    def test_init_saves(self):
        c, ch = self.console(['R0(config)#', 'R1(config)#', 'R1#', 'Building configuration...\n[OK]\nR1#'])
        c.initialize(['hostname R1'])
        self.assertEqual(ch.sendall.call_args.args[0], 'write memory\r')

    def test_init_provisions_local_ssh_login_before_save(self):
        c = Console(MagicMock())
        c.command = MagicMock(return_value='[OK]\n')
        c.initialize(['hostname R0'], username='admin', password='test-password')
        commands = [call.args[0] for call in c.command.call_args_list]
        self.assertEqual(commands[-7:], [
            'configure terminal', 'username admin privilege 15 password 0 test-password',
            'line vty 0 4', 'login local', 'transport input ssh', 'end', 'write memory'])

    def test_init_uses_default_aaa_login_after_enabling_aaa_new_model(self):
        c = Console(MagicMock())
        c.command = MagicMock(return_value='[OK]\n')
        c.initialize(['aaa new-model', 'aaa authentication login default local'],
                     username='admin', password='test-password')
        commands = [call.args[0] for call in c.command.call_args_list]
        self.assertEqual(commands[-7:], [
            'configure terminal', 'username admin privilege 15 password 0 test-password',
            'line vty 0 4', 'login authentication default',
            'transport input ssh', 'end', 'write memory'])
    def test_init_rejects_credential_command_injection_before_changes(self):
        c = Console(MagicMock())
        c.command = MagicMock()
        with self.assertRaises(ValueError):
            c.initialize(['hostname R0'], username='admin', password='bad\nreload')
        c.command.assert_not_called()
