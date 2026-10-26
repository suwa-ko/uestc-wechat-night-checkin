import hashlib
from contextlib import contextmanager
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sync_backups as sync

NAME = 'wechat-checkin-20261024T212019+0800.tar.gz.gpg'


@contextmanager
def owned_temp():
    parent = Path(__file__).resolve().parent / '.test-sync-temp'
    parent.mkdir(exist_ok=True)
    temporary = tempfile.TemporaryDirectory(dir=parent)
    assert Path(temporary.name).resolve().is_relative_to(parent.resolve())
    try:
        yield temporary.name
    finally:
        temporary.cleanup()


class SyncTests(unittest.TestCase):
    def test_receipt_follows_hash_verification_and_records_only_archive_metadata(self):
        with owned_temp() as temp:
            root = Path(temp).resolve()
            (root / 'backup-target.json').write_text(json.dumps({'owner': sync.OWNER}))
            item = {'name': NAME, 'bytes': 6, 'sha256': hashlib.sha256(b'abcdef').hexdigest()}
            response = Mock(returncode=0, stdout=b'synthetic-backup-key-' + b'a' * 44)
            process = Mock(stdout=io.BytesIO(b'abcdef'))
            process.wait.return_value = 0
            process.poll.return_value = 0
            def acknowledge(directory, archive):
                self.assertEqual(sync.digest(directory / archive['name']), archive['sha256'])
                self.assertFalse((directory / (archive['name'] + '.partial')).exists())
            with patch.object(sync, 'manifest', return_value=[item]), \
                 patch.object(sync.subprocess, 'run', return_value=response), \
                 patch.object(sync.subprocess, 'Popen', return_value=process), \
                 patch.object(sync, 'acknowledge', side_effect=acknowledge) as ack:
                sync.run(root, True)
            ack.assert_called_once()
            self.assertTrue(json.loads((root / 'sync-status.json').read_text())['server_acknowledged'])

    def test_corrupt_download_never_sends_success_receipt(self):
        with owned_temp() as temp:
            root = Path(temp).resolve()
            (root / 'backup-target.json').write_text(json.dumps({'owner': sync.OWNER}))
            item = {'name': NAME, 'bytes': 3, 'sha256': hashlib.sha256(b'good').hexdigest()}
            response = Mock(returncode=0, stdout=b'synthetic-backup-key-' + b'a' * 44)
            process = Mock(stdout=io.BytesIO(b'bad'))
            process.wait.return_value = 0
            process.poll.return_value = 0
            with patch.object(sync, 'manifest', return_value=[item]), \
                 patch.object(sync.subprocess, 'run', return_value=response), \
                 patch.object(sync.subprocess, 'Popen', return_value=process), patch.object(sync, 'acknowledge') as ack:
                with self.assertRaisesRegex(RuntimeError, 'BACKUP_HASH_MISMATCH'):
                    sync.run(root, True)
            ack.assert_not_called()

    def test_acknowledgement_failure_does_not_claim_success(self):
        item = {'name': NAME, 'bytes': 6, 'sha256': 'a' * 64}
        with patch.object(sync.subprocess, 'run', return_value=Mock(returncode=1)) as remote:
            with self.assertRaisesRegex(RuntimeError, 'REMOTE_SYNC_ACK_FAILED'):
                sync.acknowledge(Path('D:/synthetic'), item)
        compile(remote.call_args.kwargs['input'].decode(), '<receipt>', 'exec')

    def test_resume_appends_only_missing_bytes_and_verifies_hash(self):
        with owned_temp() as temp:
            root = Path(temp).resolve()
            (root / (NAME + '.partial')).write_bytes(b'abc')
            item = {'name': NAME, 'bytes': 6, 'sha256': hashlib.sha256(b'abcdef').hexdigest()}
            process = Mock(stdout=io.BytesIO(b'def'))
            process.wait.return_value = 0
            process.poll.return_value = 0
            with patch.object(sync.subprocess, 'Popen', return_value=process) as popen:
                self.assertTrue(sync.pull(root, item))
            self.assertIn('tail -c +4', popen.call_args.args[0][-1])
            self.assertEqual((root / NAME).read_bytes(), b'abcdef')
            self.assertFalse((root / (NAME + '.partial')).exists())

    def test_existing_verified_archive_is_not_downloaded_again(self):
        with owned_temp() as temp:
            root = Path(temp).resolve()
            (root / NAME).write_bytes(b'abcdef')
            item = {'name': NAME, 'bytes': 6, 'sha256': hashlib.sha256(b'abcdef').hexdigest()}
            with patch.object(sync.subprocess, 'Popen') as popen:
                self.assertFalse(sync.pull(root, item))
            popen.assert_not_called()

    def test_wrong_hash_never_promotes_partial_archive(self):
        with owned_temp() as temp:
            root = Path(temp).resolve()
            item = {'name': NAME, 'bytes': 3, 'sha256': hashlib.sha256(b'good').hexdigest()}
            process = Mock(stdout=io.BytesIO(b'bad'))
            process.wait.return_value = 0
            process.poll.return_value = 0
            with patch.object(sync.subprocess, 'Popen', return_value=process):
                with self.assertRaisesRegex(RuntimeError, 'BACKUP_HASH_MISMATCH'):
                    sync.pull(root, item)
            self.assertFalse((root / NAME).exists())

    def test_remote_path_traversal_is_rejected(self):
        data = [{'name': '../../sensitive', 'bytes': 1, 'sha256': 'a' * 64}]
        response = Mock(returncode=0, stdout=json.dumps(data).encode())
        with patch.object(sync.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(RuntimeError, 'INVALID_MANIFEST'):
                sync.manifest()

    def test_existing_local_backups_survive_empty_server_staging(self):
        with owned_temp() as temp:
            root = Path(temp).resolve()
            (root / 'backup-target.json').write_text(json.dumps({'owner': sync.OWNER}))
            (root / NAME).write_bytes(b'local archive')
            (root / 'archive-catalog.json').write_text(json.dumps({NAME: {'sha256': hashlib.sha256(b'local archive').hexdigest()}}))
            config = root / 'config-snapshot-20261024T212431+0800.tar.gz.gpg'
            config.write_bytes(b'keep this source backup')
            response = Mock(returncode=0, stdout=b'synthetic-backup-key-' + b'a' * 44)
            with patch.object(sync, 'manifest', return_value=[]), patch.object(sync.subprocess, 'run', return_value=response):
                sync.run(root, True)
            self.assertTrue(config.exists())
            self.assertEqual(json.loads((root / 'sync-status.json').read_text())['status'], 'success')


if __name__ == '__main__':
    unittest.main()
