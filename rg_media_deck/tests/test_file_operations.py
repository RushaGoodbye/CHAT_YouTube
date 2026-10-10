import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import file_operations as ops


class SafeFileTests(unittest.TestCase):
    def test_mixed_windows_path_and_cyrillic(self):
        with patch.object(ops.os, 'name', 'nt'):
            self.assertEqual(
                ops.recycle_path('F:/ФАКТАЖ\\ВОЙНА пришла в рф/клип.mp4'),
                'F:\\ФАКТАЖ\\ВОЙНА пришла в рф\\клип.mp4')
            self.assertEqual(ops.recycle_path('\\\\?\\F:\\Новини\\x.mp4'),
                             'F:\\Новини\\x.mp4')
            for bad in ('x.mp4', 'F:clip.mp4', 'F:\\', '\\\\.\\PhysicalDrive0'):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    ops.recycle_path(bad)

    def test_failed_recycle_leaves_original_intact(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root, 'clip.mp4')
            path.write_bytes(b'original bytes')
            with patch.object(ops, 'send2trash', side_effect=OSError('recycle failed')):
                with self.assertRaises(OSError):
                    ops.trash_file(str(path))
            self.assertEqual(path.read_bytes(), b'original bytes')

    def test_rename_preserves_original_extension(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root, 'old.mp4')
            source.write_bytes(b'video')
            renamed = Path(ops.rename_file(str(source), 'Мій кліп'))
            self.assertEqual(renamed.name, 'Мій кліп.mp4')
            self.assertEqual(renamed.read_bytes(), b'video')
            self.assertFalse(source.exists())

    def test_rename_rejects_invalid_names_and_collisions(self):
        for name in ('', '..', 'a/b', 'CON', 'LPT1', 'bad?'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ops.validated_new_name('clip.mp4', name)
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root,'first.mp4'), Path(root,'second.mp4')
            a.write_bytes(b'a'); b.write_bytes(b'b')
            with self.assertRaises(FileExistsError):
                ops.rename_file(str(a), 'second')
            self.assertEqual(b.read_bytes(), b'b')

    def test_move_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            left, right = Path(root,'left'), Path(root,'right')
            left.mkdir(); right.mkdir()
            src, dest = left/'clip.mp4', right/'clip.mp4'
            src.write_bytes(b'source'); dest.write_bytes(b'keep')
            with self.assertRaises(FileExistsError):
                ops.move_file(str(src), str(right))
            self.assertEqual(dest.read_bytes(), b'keep')
            dest.unlink()
            self.assertEqual(Path(ops.move_file(str(src), str(right))), dest)
            self.assertEqual(dest.read_bytes(), b'source')


if __name__ == '__main__':
    unittest.main()
