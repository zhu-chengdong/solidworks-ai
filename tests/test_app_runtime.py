from pathlib import Path
import tempfile
import unittest

from app_runtime import layout


class PortablePathsTests(unittest.TestCase):
    def test_frozen_paths_survive_relocation_and_keep_data_outside_program(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            resources, data, command, args = layout(frozen=True,
                executable=base/'moved folder'/'SolidWorksAI.exe',
                resource_root=base/'moved folder'/'_internal',
                environment={'LOCALAPPDATA': str(base/'different user')})
            self.assertEqual(command, (base/'moved folder'/'SolidWorksMCP.exe').resolve())
            self.assertEqual(data, (base/'different user'/'SolidWorksAI').resolve())
            self.assertFalse(data.is_relative_to(resources))
            self.assertEqual(args, [])

    def test_source_clone_uses_active_python_without_requiring_original_venv(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _, data, command, args = layout(frozen=False, resource_root=root,
                executable=root/'python.exe', environment={})
            self.assertEqual(data, root.resolve())
            self.assertEqual(command, (root/'python.exe').resolve())
            self.assertEqual(args, [str(root.resolve()/'server.py')])

    def test_test_data_override_must_be_absolute(self):
        with self.assertRaises(ValueError):
            layout(environment={'SOLIDWORKS_AI_DATA_HOME':'relative'}, frozen=True)
