import json
from pathlib import Path
import tempfile
import unittest

from release_tools.build import copy_public


class PublicSourceTests(unittest.TestCase):
    def test_source_distribution_contains_no_private_state_or_machine_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'public'
            copy_public(target)
            for name in ('runtime','artifacts','.venv','.env.local','providers.local.json','configs'):
                self.assertFalse((target/name).exists(),name)
            manifest=json.loads((target/'vendor/source-manifest.json').read_text(encoding='utf-8'))
            self.assertTrue(manifest['source'].startswith('https://github.com/'))
            self.assertTrue((target/'.github/workflows/build-windows.yml').is_file())
            self.assertNotIn('PyMuPDF',(target/'requirements.txt').read_text())
            self.assertTrue((target/'LICENSE').is_file())
