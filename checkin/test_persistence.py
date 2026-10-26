import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import backup
import checkin
import health


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patcher = patch.object(checkin, 'STATE', self.root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def test_health_waits_two_checks_and_deduplicates(self):
        with patch.object(health, 'collect', return_value=[('wechat-web_stopped', '微信未运行')]):
            health.run({})
            self.assertEqual(len(list(self.root.glob('*-notice.json'))), 0)
            health.run({})
            health.run({})
            self.assertEqual(len(list(self.root.glob('*-notice.json'))), 1)
        with patch.object(health, 'collect', return_value=[]):
            health.run({})
        self.assertEqual(checkin.read(self.root / 'health.json')['notified_fingerprint'], '')

    def test_backup_excludes_key_and_logs_but_keeps_match_template(self):
        import tarfile
        for name in ['host/etc/wechat-checkin/backup-passphrase', 'wechat-profile/probe-artifacts/client.log', 'host/runtime/debugger.log']:
            self.assertIsNone(backup.excluded(tarfile.TarInfo(name)))
        self.assertIsNotNone(backup.excluded(tarfile.TarInfo('host/usr/local/lib/wechat-checkin/school-logo.png')))
        self.assertIsNotNone(backup.excluded(tarfile.TarInfo('wechat-profile/account.db')))
        self.assertIsNone(backup.excluded(tarfile.TarInfo('wechat-profile/xwechat_files/test/db_storage/message')))
        self.assertIsNone(backup.excluded(tarfile.TarInfo('wechat-profile/xwechat_files/test/db_storage/message/message_0.db')))
        self.assertIsNotNone(backup.excluded(tarfile.TarInfo('host/usr/local/lib/wechat-checkin/ui-templates/clear-confirm.png')))

    def test_recovery_unpauses_only_recorded_container(self):
        marker = self.root / 'pause.json'
        checkin.save(marker, {'container_id': 'owned-container'})
        result = type('R', (), {'stdout': json.dumps([{'Id': 'different-container', 'State': {'Paused': True}}])})()
        with patch.object(backup, 'PAUSED', marker), patch.object(backup, 'command', return_value=result) as command:
            with self.assertRaisesRegex(RuntimeError, 'RECOVERY_CONTAINER_CHANGED'):
                backup.recover()
        command.assert_called_once_with('docker', 'inspect', 'wechat-web')


if __name__ == '__main__':
    unittest.main()
