from datetime import datetime
import unittest

import checkin
import health


class HealthMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.moment = datetime(2026, 10, 26, 14, 0, tzinfo=checkin.TZ).timestamp()
        self.backup = {'status': 'success', 'timestamp': self.moment - 3600, 'archive': '/var/backups/wechat-checkin/latest.gpg'}
        self.cleanup = {'status': 'success', 'chat_records_cleared': True,
                        'time': datetime.fromtimestamp(self.moment - 3600, checkin.TZ).isoformat()}
        self.sync = {'archive': 'latest.gpg', 'timestamp': self.moment - 300}

    def codes(self, **overrides):
        values = dict(backup=self.backup, cleanup=self.cleanup, sync=self.sync, attempts={}, moment=self.moment)
        values.update(overrides)
        return {code for code, _ in health.maintenance_issues(**values)}

    def test_old_successful_cleanup_is_not_reported_healthy(self):
        self.cleanup['time'] = datetime.fromtimestamp(self.moment - 37 * 3600, checkin.TZ).isoformat()
        self.assertIn('cache_cleanup_stale', self.codes())

    def test_latest_backup_requires_matching_receipt_after_grace(self):
        self.backup['timestamp'] = self.moment - 11 * 3600
        self.assertNotIn('backup_sync_lag', self.codes(sync={}))
        self.backup['timestamp'] = self.moment - 13 * 3600
        self.assertIn('backup_sync_lag', self.codes(sync={'archive': 'older.gpg', 'timestamp': self.moment}))
        self.assertNotIn('backup_sync_lag', self.codes())

    def test_old_receipt_is_stale_even_when_archive_matches(self):
        self.sync['timestamp'] = self.moment - 37 * 3600
        self.assertIn('backup_sync_stale', self.codes())

    def test_skipped_maintenance_cannot_stay_green_forever(self):
        attempt = {'status': 'deferred', 'timestamp': self.moment - 16 * 60}
        self.assertIn('cleanup_retry_exhausted', self.codes(attempts={'cleanup': attempt}))
        attempt['status'] = 'success'
        self.assertNotIn('cleanup_retry_exhausted', self.codes(attempts={'cleanup': attempt}))


if __name__ == '__main__':
    unittest.main()
