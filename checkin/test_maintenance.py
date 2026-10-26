import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import backup
import checkin
import cleanup


class MaintenanceTests(unittest.TestCase):
    def test_real_lock_contention_waits_then_acquires(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'run.lock'
            code = ('import fcntl,sys,time; f=open(sys.argv[1],"a"); '
                    'fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); time.sleep(.4)')
            child = subprocess.Popen([sys.executable, '-c', code, str(path)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                started = time.monotonic()
                with path.open('a') as handle:
                    self.assertTrue(checkin.acquire_lock(handle, wait_seconds=2))
                self.assertGreater(time.monotonic() - started, .2)
            finally:
                child.wait(timeout=5)
                child.stdout.close()

    def test_held_lock_times_out_without_stealing_it(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'run.lock'
            with path.open('a') as owner, path.open('a') as contender:
                fcntl.flock(owner, fcntl.LOCK_EX)
                started = time.monotonic()
                self.assertFalse(checkin.acquire_lock(contender, wait_seconds=.2))
                self.assertLess(time.monotonic() - started, 1)

    def test_busy_maintenance_requests_retry_and_preserves_last_success(self):
        for module, job, argv in [(backup, 'backup', ['backup.py', 'run']),
                                  (cleanup, 'cleanup', ['cleanup.py', 'run'])]:
            with self.subTest(job=job), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                previous = {'status': 'success', 'time': '2026-10-26T04:20:00+08:00'}
                checkin.save(root / ('last-' + job + '.json'), previous)
                with patch.object(checkin, 'STATE', root), patch.object(backup, 'BACKUPS', root), \
                     patch.object(checkin, 'acquire_lock', return_value=False), \
                     patch('sys.argv', argv), self.assertRaises(SystemExit) as stopped:
                    module.main()
                self.assertEqual(stopped.exception.code, 75)
                self.assertEqual(checkin.read(root / ('last-' + job + '.json')), previous)
                self.assertEqual(checkin.read(root / (job + '-attempt.json'))['status'], 'deferred')


if __name__ == '__main__':
    unittest.main()
