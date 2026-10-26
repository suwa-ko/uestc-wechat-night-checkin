from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import checkin


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = patch.object(checkin, 'STATE', self.root)
        self.state.start()
        self.health = patch('health.run')
        self.health.start()
        key = self.root / 'key'
        key.write_text('synthetic-test-key')
        self.config = {'astrbot': {'key_file': str(key), 'url': 'http://127.0.0.1:6185/api/v1/im/messages', 'umo': 'owner:FriendMessage:123'}}
        self.payload = {'message': 'synthetic failure', 'kind': 'failure', 'day': '2026-10-24'}
        self.response = Mock()
        self.response.__enter__ = Mock(return_value=self.response)
        self.response.__exit__ = Mock(return_value=False)
        self.response.read.return_value = b'{"status":"ok"}'
        self.opener = Mock()
        self.opener.open.return_value = self.response

    def tearDown(self):
        self.health.stop()
        self.state.stop()
        self.temp.cleanup()

    def test_render_success_sends_only_one_image(self):
        rendered = Mock(returncode=0, stdout='{"attachment_id":"00000000-0000-0000-0000-000000000001"}')
        with patch.object(checkin, 'run', return_value=rendered), patch.object(checkin.urllib.request, 'build_opener', return_value=self.opener):
            self.assertEqual(checkin.send_notice(self.config, self.payload), 'accepted')
        self.opener.open.assert_called_once()
        body = json.loads(self.opener.open.call_args.args[0].data)
        self.assertEqual(body['message'], [{'type': 'image', 'attachment_id': '00000000-0000-0000-0000-000000000001'}])

    def test_render_failure_sends_only_one_text(self):
        with patch.object(checkin, 'run', return_value=Mock(returncode=1)), patch.object(checkin.urllib.request, 'build_opener', return_value=self.opener):
            self.assertEqual(checkin.send_notice(self.config, self.payload), 'accepted')
        self.opener.open.assert_called_once()
        self.assertEqual(json.loads(self.opener.open.call_args.args[0].data)['message'], 'synthetic failure')

    def test_unknown_delivery_is_not_retried(self):
        path = self.root / '2026-10-24-notice.json'
        checkin.save(path, {'status': 'pending', 'payload': self.payload})
        with patch.object(checkin, 'send_notice', return_value='unknown') as sender:
            checkin.deliver(self.config, '2026-10-24')
            checkin.deliver(self.config, '2026-10-24')
        sender.assert_called_once()

    def test_stale_inflight_is_not_retried(self):
        checkin.save(self.root / '2026-10-24-notice.json', {'status': 'inflight', 'payload': self.payload})
        with patch.object(checkin, 'send_notice') as sender:
            checkin.deliver(self.config, '2026-10-24')
        sender.assert_not_called()

    def test_submit_intent_blocks_second_click(self):
        checkin.save(self.root / '2026-10-24.json', {'confirmIntent': True, 'outcome': 'unknown'})
        config = self.root / 'config.json'
        checkin.save(config, self.config)
        with patch.object(checkin, 'CONFIG', config), patch.object(checkin, 'now', return_value=datetime(2026, 10, 24, 21, 1, tzinfo=checkin.TZ)), patch('sys.argv', ['checkin.py', 'submit']), patch.object(checkin, 'prepare') as prepare:
            checkin.main()
        prepare.assert_not_called()

    def test_outside_window_does_not_open_wechat(self):
        config = self.root / 'config.json'
        checkin.save(config, self.config)
        with patch.object(checkin, 'CONFIG', config), patch.object(checkin, 'now', return_value=datetime(2026, 10, 24, 20, 59, tzinfo=checkin.TZ)), patch('sys.argv', ['checkin.py', 'submit']), patch.object(checkin, 'prepare') as prepare:
            checkin.main()
        prepare.assert_not_called()

    def test_credentials_are_redacted(self):
        value = checkin.sanitize('ticket=example-value https://school.invalid/?token=x ' + 'a' * 40)
        self.assertNotIn('example-value', value)
        self.assertNotIn('token=x', value)
        self.assertNotIn('a' * 40, value)

    def test_watchdog_reports_crash_after_confirm_intent(self):
        checkin.save(self.root / '2026-10-24.json', {'confirmIntent': True, 'outcome': 'unknown'})
        config = self.root / 'config.json'
        checkin.save(config, self.config)
        with patch.object(checkin, 'CONFIG', config), patch.object(checkin, 'now', return_value=datetime(2026, 10, 24, 21, 5, tzinfo=checkin.TZ)), patch('sys.argv', ['checkin.py', 'watchdog']), patch.object(checkin, 'queue') as queue:
            checkin.main()
        queue.assert_called_once_with(self.config, '2026-10-24', 'RESULT_UNCONFIRMED', None)

    def test_no_open_page_bootstraps_miniapp(self):
        snapshot = {'hasTicket': True, 'businessDate': '2026-10-24', 'locationActive': True, 'mapMatches': True}
        with patch.object(checkin, 'debugger'), patch.object(checkin, 'location'), patch.object(checkin, 'node', side_effect=[checkin.Failure('CDP_TIMEOUT_TARGET.GETTARGETS'), {}, snapshot]), patch('ui.bootstrap') as bootstrap:
            self.assertEqual(checkin.prepare(self.config), snapshot)
        bootstrap.assert_called_once()

    def test_auth_pause_does_not_attempt_login_again(self):
        checkin.save(self.root / 'control.json', {'auth_paused': True})
        config = self.root / 'config.json'
        checkin.save(config, self.config)
        with patch.object(checkin, 'CONFIG', config), patch.object(checkin, 'now', return_value=datetime(2026, 10, 24, 21, 1, tzinfo=checkin.TZ)), patch('sys.argv', ['checkin.py', 'submit']), patch.object(checkin, 'prepare') as prepare:
            checkin.main()
        prepare.assert_not_called()

    def test_pending_notice_is_retried_outside_checkin_window(self):
        checkin.save(self.root / '2026-10-23-notice.json', {'status': 'pending', 'payload': self.payload})
        config = self.root / 'config.json'
        checkin.save(config, self.config)
        with patch.object(checkin, 'CONFIG', config), patch.object(checkin, 'now', return_value=datetime(2026, 10, 24, 10, 0, tzinfo=checkin.TZ)), patch('sys.argv', ['checkin.py', 'watchdog']), patch.object(checkin, 'deliver') as deliver, patch.object(checkin, 'prepare') as prepare:
            checkin.main()
        deliver.assert_called_once_with(self.config, '2026-10-23')
        prepare.assert_not_called()


if __name__ == '__main__':
    unittest.main()
