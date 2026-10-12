import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from library import MediaItem, load_settings, save_settings
from live_library import (FileIdentityIndex, changed_files,
                          keep_offline_entries, relocated_path)
from streamdeck_hotkeys import (ACTIONS, DEFAULT_BINDINGS, parse_hotkey,
                                validated_bindings, hotkey_guide)
from broadcast_guard import BroadcastGuard, ResourceSnapshot, permit_preload
from update_rollback import (WATCHDOG_SCRIPT, save_rollback_manifest,
                             verified_saved_rollback)


class LibraryMoveTests(unittest.TestCase):
    def test_directory_moves_keep_relative_paths(self):
        self.assertEqual(
            relocated_path('D:/ФАКТАЖ/Старе/ABC/movie.mp4',
                           'D:/ФАКТАЖ/Старе', 'D:/ФАКТАЖ/Нове'),
            os.path.normpath('D:/ФАКТАЖ/Нове/ABC/movie.mp4'))
        self.assertIsNone(relocated_path('D:/Друге/file.mp4',
                                         'D:/ФАКТАЖ/Старе', 'D:/ФАКТАЖ/Нове'))

    def test_same_volume_move_matches_stable_inode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old, new = root / 'старий.mp4', root / 'новий.mp4'
            old.write_bytes(b'picture frames')
            index = FileIdentityIndex()
            index.seed([MediaItem(str(old), old.name, 'video', 14)])
            old.rename(new)
            self.assertEqual(index.match_new_file(str(new)), str(old))
            self.assertIsNone(index.match_new_file(str(new)))

    def test_missing_drive_keeps_metadata_until_reconnection(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = str(Path(folder) / 'unmounted')
            old_path = str(Path(missing) / 'кліп.mp4')
            old = MediaItem(old_path, 'кліп.mp4', 'video', 1234)
            self.assertEqual(keep_offline_entries([], [old], [missing]), [old])
            # Ordinary file event on unavailable root must not delete entries.
            self.assertEqual(changed_files([old], {old_path}, [missing]), [old])

    def test_modified_file_uses_new_size_without_losing_other_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / 'a.mp4'
            file.write_bytes(b'old')
            items = [MediaItem(str(file), file.name, 'video', 3)]
            file.write_bytes(b'new content')
            result = changed_files(items, {str(file)}, [folder])
            self.assertEqual(result[0].size, 11)


class StreamDeckTests(unittest.TestCase):
    def test_seven_actions_include_two_collections(self):
        self.assertEqual(len(ACTIONS), 13)
        self.assertIn('collection_1', ACTIONS)
        self.assertIn('collection_2', ACTIONS)
        self.assertIn('F12', hotkey_guide())

    def test_custom_keys_and_reserved_combinations(self):
        name, mods, vk = parse_hotkey('alt+ctrl+F5')
        self.assertEqual(name, 'Ctrl+Alt+F5')
        self.assertEqual(vk, 0x74)
        for invalid in ('F6', 'Shift+F6', 'Win+Ctrl+F7',
                        'Ctrl+Alt+F25', 'Ctrl+Ctrl+F4', 'Alt+F1'):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_hotkey(invalid)

    def test_conflicting_keys_not_registered_twice(self):
        parsed = validated_bindings({
            'play_pause': 'Ctrl+Alt+F6', 'stop': 'Ctrl+Alt+F6'})
        self.assertIn('play_pause', parsed)
        self.assertNotIn('stop', parsed)
        self.assertEqual(len(set(parsed.values())), len(parsed))

    def test_config_roundtrip_old_settings(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'settings.json'
            save_settings({'roots': [], 'favorites': [],
                           'streamdeck_bindings': {'mute': 'Ctrl+Alt+F1'},
                           'deck_collections': {'collection_1': 'НПЗ'}}, path)
            settings = load_settings(path)
            self.assertEqual(settings['streamdeck_bindings']['mute'], 'Ctrl+Alt+F1')
            self.assertEqual(settings['deck_collections']['collection_1'], 'НПЗ')
            self.assertIn('stop', settings['streamdeck_bindings'])


class BroadcastSafetyTests(unittest.TestCase):
    def test_resource_fails_closed(self):
        self.assertFalse(permit_preload(ResourceSnapshot(cpu=96)))
        self.assertFalse(permit_preload(ResourceSnapshot(physical_ram=93)))
        self.assertFalse(permit_preload(ResourceSnapshot(process_bytes=2_000_000_000)))
        self.assertTrue(permit_preload(ResourceSnapshot(cpu=20, physical_ram=45,
                                                        process_bytes=300_000_000)))

    def test_resource_metrics_and_status_json(self):
        with tempfile.TemporaryDirectory() as folder:
            guard = BroadcastGuard()
            guard.switch_count = 550
            guard.decoder_errors = 3
            guard.snapshot = ResourceSnapshot(cpu=45, physical_ram=56,
                                               process_bytes=500_000_000)
            path = guard.write_state(Path(folder), 'playing', 'D:/Раша/кліп.mp4')
            import json
            state = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(state['switch_count'], 550)
            self.assertEqual(state['state'], 'playing')
            self.assertEqual(state['file_name'], 'кліп.mp4')

    def test_500_exclusive_audio_retirements_mute_before_stop(self):
        # Verify original PlayerSurface shutdown order with 500 transitions,
        # without playing sound or opening any external device.
        from app import PlayerSurface
        for i in range(500):
            events = []
            class Audio:
                def setMuted(self, flag): events.append(('muted', flag))
                def setVolume(self, level): events.append(('volume', level))
                def deleteLater(self): events.append(('audio_gc', True))
            class Player:
                def stop(self): events.append(('stop', True))
                def setSource(self, value): events.append(('source', True))
                def setAudioOutput(self, value): events.append(('detach_audio', True))
                def setVideoOutput(self, value): events.append(('detach_video', True))
                def deleteLater(self): events.append(('player_gc', True))
            PlayerSurface._retire(None, Player(), Audio())
            self.assertEqual(events[0], ('muted', True))
            self.assertEqual(events[1], ('volume', 0.0))
            self.assertEqual(events[2], ('stop', True))


class RollbackSafetyTests(unittest.TestCase):
    def test_watchdog_requires_both_signatures_and_verifies_new_exe(self):
        for needed in ('Get-FileHash', 'OldInstaller', 'NewInstaller',
                       '--selftest', 'ROLLBACK:', 'OldPid'):
            self.assertIn(needed, WATCHDOG_SCRIPT)
        self.assertLess(WATCHDOG_SCRIPT.index('Verified $NewInstaller'),
                        WATCHDOG_SCRIPT.index('Install $NewInstaller'))

    def test_rollback_manifest_fails_on_corrupted_installer(self):
        with tempfile.TemporaryDirectory() as folder:
            from update_rollback import storage
            root = Path(folder)
            installer = root / 'RG_Media_Deck_Previous_0.4.0.exe'
            installer.write_bytes(b'MZ' + b'a' * 2000)
            import hashlib
            sha = hashlib.sha256(installer.read_bytes()).hexdigest()
            with patch('update_rollback.storage', return_value=root):
                save_rollback_manifest('0.4.0', installer, sha)
                self.assertEqual(verified_saved_rollback()[0], '0.4.0')
                installer.write_bytes(b'corruption')
                self.assertIsNone(verified_saved_rollback())


if __name__ == '__main__':
    unittest.main()
