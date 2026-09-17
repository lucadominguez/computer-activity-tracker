import contextlib
import io
import tempfile
import unittest
from pathlib import Path


class LegacySafetyTests(unittest.TestCase):
    def test_legacy_smoke_uses_a_disposable_database(self):
        import os
        import runpy
        from unittest.mock import patch

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CCA_HOME": tmp}):
            namespace = runpy.run_path(str(root / "smoke_test.py"), run_name="isolated_import")
            self.assertNotEqual(Path(namespace["CCA_HOME"]), root / "data")
            self.assertNotEqual(Path(namespace["CCA_HOME"]), Path(tmp))
            namespace["_TEST_DATA"].cleanup()

    def test_self_test_never_replaces_existing_history(self):
        from windows.windows_activity_tracker import self_test

        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "activity.sqlite3"
            original = b"Private existing database sentinel; must not be deleted"
            database.write_bytes(original)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self_test(tmp), 0)
            self.assertEqual(database.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
