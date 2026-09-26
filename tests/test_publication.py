"""Release integrity and safe failure checks; full numerical reproduction is a separate CI step."""
import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('paper171', Path(__file__).resolve().parents[1] / 'publication/side2026/reproduce.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublicationTests(unittest.TestCase):
    def test_corrupted_bundle_is_rejected_before_processing(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'data.tar.gz'
            p.write_bytes(b'changed')
            p.with_suffix('.gz.sha256').write_text('0' * 64)
            with self.assertRaisesRegex(ValueError, 'Bundle checksum mismatch'):
                module.load_bundle(p)

    def test_parent_traversal_is_rejected_even_with_matching_outer_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'data.tar.gz'
            with tarfile.open(p, 'w:gz') as tar:
                info = tarfile.TarInfo('../outside')
                info.size = 4
                tar.addfile(info, io.BytesIO(b'test'))
            p.with_suffix('.gz.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'Unsafe archive member'):
                module.load_bundle(p)
            self.assertFalse((Path(tmp).parent / 'outside').exists())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            sentinel = p / 'result.txt'
            sentinel.write_text('keep')
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                module.reproduce(p, p / 'unused.tar.gz')
            self.assertEqual('keep', sentinel.read_text())

if __name__ == '__main__':
    unittest.main()
