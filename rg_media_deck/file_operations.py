"""Safe file management. Never permanently delete media."""
from __future__ import annotations
import ntpath
import os
import shutil
from pathlib import Path
from send2trash import send2trash

_INVALID = set('<>:"/\\|?*')
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL',
             *(f'COM{i}' for i in range(1, 10)),
             *(f'LPT{i}' for i in range(1, 10))}


def recycle_path(path: str) -> str:
    """Canonicalize mixed Windows separators before passing to Recycle Bin."""
    if not isinstance(path, str) or not path.strip() or '\0' in path:
        raise ValueError('Некоректний шлях до файлу')
    if os.name != 'nt':
        return os.path.abspath(path)
    result = ntpath.normpath(path)
    if result.startswith('\\\\.\\'):
        raise ValueError('Шляхи пристроїв не підтримуються')
    if result.startswith('\\\\?\\UNC\\'):
        result = '\\\\' + result[8:]
    elif result.startswith('\\\\?\\'):
        result = result[4:]
    result = ntpath.normpath(result)
    drive, tail = ntpath.splitdrive(result)
    if not drive or not ntpath.isabs(result) or tail in ('', '\\'):
        raise ValueError('Потрібен абсолютний шлях до файлу')
    return result


def trash_file(path: str) -> None:
    path = recycle_path(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    # Recycle-only operation; never fallback to os.remove/unlink.
    send2trash(path)


def validated_new_name(original: str, typed: str) -> str:
    stem = typed.strip()
    if not stem or stem in ('.', '..') or stem.endswith(('.', ' ')):
        raise ValueError('Некоректна назва файлу')
    if any(ch in _INVALID or ord(ch) < 32 for ch in stem):
        raise ValueError('Назва містить заборонені символи')
    if stem.upper().split('.')[0] in _RESERVED:
        raise ValueError('Зарезервована назва Windows')
    suffix = Path(original).suffix
    if len((stem + suffix).encode('utf-8')) > 240:
        raise ValueError('Завелика назва файлу')
    return stem + suffix


def rename_file(path: str, typed: str) -> str:
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(path)
    dest = source.with_name(validated_new_name(source.name, typed))
    if os.path.normcase(str(dest)) == os.path.normcase(str(source)):
        return str(source)
    if dest.exists():
        raise FileExistsError(f'Файл вже існує: {dest.name}')
    source.rename(dest)
    return str(dest)


def move_file(path: str, folder: str) -> str:
    source = Path(path)
    dest_dir = Path(folder)
    if not source.is_file():
        raise FileNotFoundError(path)
    if not dest_dir.is_dir():
        raise NotADirectoryError(folder)
    dest = dest_dir / source.name
    if os.path.normcase(os.path.abspath(dest)) == os.path.normcase(os.path.abspath(source)):
        return str(source)
    if dest.exists():
        raise FileExistsError(f'Файл вже існує: {dest}')
    return str(shutil.move(str(source), str(dest)))
