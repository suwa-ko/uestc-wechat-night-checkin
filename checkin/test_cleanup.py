import os
from pathlib import Path
import tempfile
import time
import unittest

import cleanup


class CleanupTests(unittest.TestCase):
    def test_only_old_disposable_files_are_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cache = root / 'xwechat_files/test-account/cache'
            cache.mkdir(parents=True)
            paths = {name: cache / name for name in ['old.tmp', 'recent.tmp', 'Cookies', 'account.db']}
            paths['history'] = root / 'xwechat_files/test-account/db_storage/message/history.db'
            paths['runtime'] = root / '.xwechat/radium/users/test-account/applet/runtime.so'
            for path in paths.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'test')
                os.utime(path, (time.time() - 60 * 86400, time.time() - 60 * 86400))
            os.utime(paths['recent.tmp'], None)
            result = cleanup.clean(root, time.time(), False)
            self.assertEqual(result['removed_files'], 1)
            self.assertFalse(paths['old.tmp'].exists())
            for name in ['recent.tmp', 'Cookies', 'account.db', 'history', 'runtime']:
                self.assertTrue(paths[name].exists(), name)

    def test_symlink_into_chat_database_is_not_followed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            account = root / 'xwechat_files/test-account'
            (account / 'db_storage').mkdir(parents=True)
            data = account / 'db_storage/data.tmp'
            data.write_bytes(b'protected')
            os.utime(data, (0, 0))
            (account / 'cache').symlink_to(account / 'db_storage', target_is_directory=True)
            result = cleanup.clean(root, time.time(), False)
            self.assertEqual(result['removed_files'], 0)
            self.assertTrue(data.exists())


if __name__ == '__main__':
    unittest.main()
