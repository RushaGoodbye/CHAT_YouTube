import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import updater


class UrlResp(io.BytesIO):
    def __init__(self, content, url):
        super().__init__(content)
        self.url = url
        self.headers = {'Content-Length': str(len(content))}

    def geturl(self):
        return self.url


class InstallerUpdateTests(unittest.TestCase):
    def fake_release(self, v='0.1.9', assets=True):
        base = 'https://github.com/RushaGoodbye/CHAT_YouTube/releases/download/rg-media-deck-v' + v + '/'
        return {'tag_name':'rg-media-deck-v' + v, 'draft':False, 'body':'Notes',
                'assets': ([{'name':updater.INSTALLER_NAME, 'browser_download_url':base+updater.INSTALLER_NAME},
                            {'name':updater.CHECKSUM_NAME, 'browser_download_url':base+updater.CHECKSUM_NAME}] if assets else [])}

    def test_release_selection(self):
        self.assertEqual(updater.select_release([self.fake_release('0.1.8'),self.fake_release('0.1.10')], '0.1.4')['version'], '0.1.10')
        self.assertIsNone(updater.select_release([self.fake_release('0.1.3')], '0.1.4'))
        self.assertIsNone(updater.select_release([self.fake_release('0.1.8', False)], '0.1.4'))
        self.assertIsNone(updater.select_release([{'tag_name':'not-rg-media-deck','assets':[]}], '0.1.4'))

    def test_reject_untrusted(self):
        rec=self.fake_release()
        rec['assets'][0]['browser_download_url']='https://evil.test/setup.exe'
        self.assertIsNone(updater.select_release([rec], '0.1.4'))
        self.assertFalse(updater.trusted_download_url('https://github.com.evil.test/RushaGoodbye/CHAT_YouTube/releases/download/x'))
        self.assertFalse(updater.trusted_download_url('http://github.com/RushaGoodbye/CHAT_YouTube/releases/download/x'))

    def test_checksum_download(self):
        data=b'MZ'+b'\0'*8192
        sha=hashlib.sha256(data).hexdigest()
        release=updater.select_release([self.fake_release()], '0.1.4')
        with tempfile.TemporaryDirectory() as folder:
            def fake_request(url,timeout=20):
                response=(sha+'  '+updater.INSTALLER_NAME+'\n').encode() if url==release['sha_url'] else data
                return UrlResp(response,'https://release-assets.githubusercontent.com/artifact')
            with patch.object(updater,'_request',side_effect=fake_request),patch.object(updater,'update_folder',return_value=Path(folder)):
                result,actual=updater.download_update(release)
                self.assertEqual(result.read_bytes(),data)
                self.assertEqual(actual,sha)

    def test_bad_hash_cleaned(self):
        release=updater.select_release([self.fake_release()], '0.1.4')
        with tempfile.TemporaryDirectory() as folder:
            def fake_request(url,timeout=20):
                data=b'0'*64 if url==release['sha_url'] else b'MZ'+b'0'*8192
                return UrlResp(data,'https://release-assets.githubusercontent.com/artifact')
            with patch.object(updater,'_request',side_effect=fake_request),patch.object(updater,'update_folder',return_value=Path(folder)):
                with self.assertRaises(ValueError):
                    updater.download_update(release)
                self.assertFalse(list(Path(folder).glob('*.part')))
                self.assertFalse(list(Path(folder).glob('*.exe')))

    def test_cancel_removes_partial(self):
        release=updater.select_release([self.fake_release()], '0.1.4')
        with tempfile.TemporaryDirectory() as folder:
            sha=hashlib.sha256(b'MZ'+b'0'*8192).hexdigest()
            def fake_request(url,timeout=20):
                return UrlResp((sha+'\n').encode() if url==release['sha_url'] else b'MZ'+b'0'*8192,'https://release-assets.githubusercontent.com/artifact')
            with patch.object(updater,'_request',side_effect=fake_request),patch.object(updater,'update_folder',return_value=Path(folder)):
                with self.assertRaises(InterruptedError):
                    updater.download_update(release,cancelled=lambda: True)
                self.assertFalse(list(Path(folder).iterdir()))


if __name__ == '__main__':
    unittest.main()
