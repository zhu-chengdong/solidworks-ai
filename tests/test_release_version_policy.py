import hashlib
from pathlib import Path
import tempfile
import unittest

from release_tools.version_policy import (require_release_version, require_source_version,
                                         require_package_pair, require_release_receipts)


class ReleaseVersionPolicyTests(unittest.TestCase):
    def test_regular_identifiers_reject_suffixes_prefixes_and_ambiguous_numbers(self):
        for version in ('0.16.0', '0.16.1', '1.0.0'):
            self.assertEqual(require_release_version(version), version)
        for version in ('0.16.0-rc1', '0.16.0-beta', 'v0.16.0', '01.16.0', '0.16', '0.16.0+build', '0.16.0\n'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                require_release_version(version)

    def test_application_version_is_read_without_importing_or_executing_the_app(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)/'webserver.py'
            source.write_text('raise RuntimeError("must not execute")\nVERSION = "0.16.0"\n', encoding='utf8')
            require_source_version('0.16.0', source)
            with self.assertRaises(ValueError):
                require_source_version('0.16.1', source)

    def test_both_packages_and_their_actual_hashes_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            names = [f'SolidWorksAI-0.16.0-{kind}.zip' for kind in ('source', 'windows-x64')]
            for name in names:
                (folder/name).write_bytes(name.encode())
            (folder/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256((folder/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in names))
            require_package_pair(folder, '0.16.0')
            (folder/names[1]).write_bytes(b'changed executable package')
            with self.assertRaises(ValueError):
                require_package_pair(folder, '0.16.0')
            (folder/names[1]).unlink()
            with self.assertRaises(ValueError):
                require_package_pair(folder, '0.16.0')

    def test_source_only_checksums_cannot_pass_the_pair_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder/'SHA256SUMS.txt').write_text('abc  SolidWorksAI-0.16.0-source.zip\n')
            with self.assertRaises(ValueError):
                require_package_pair(folder, '0.16.0')

    def test_frozen_executable_must_report_the_release_version(self):
        portable = {'status': 'passed', 'ui_health': {'version': '0.16.0'}}
        proof = {'status': 'passed', 'version': '0.16.0', 'release_channel': 'release',
                 'actual_stored_credentials_scan_passed': True, 'trials': {'real': {'bundled': True}}}
        require_release_receipts('0.16.0', portable, proof)
        with self.assertRaises(ValueError):
            require_release_receipts('0.16.1', portable, {**proof, 'version': '0.16.1'})

    def test_prerelease_or_missing_real_credential_scan_cannot_be_published(self):
        portable = {'status': 'passed', 'ui_health': {'version': '0.16.0'}}
        proof = {'status': 'passed', 'version': '0.16.0', 'release_channel': 'release',
                 'actual_stored_credentials_scan_passed': True, 'trials': {'real': {'bundled': True}}}
        for changes in ({'release_channel': 'prerelease'}, {'actual_stored_credentials_scan_passed': False}, {'trials': {}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                require_release_receipts('0.16.0', portable, {**proof, **changes})
