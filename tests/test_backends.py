import importlib.util
import os
import unittest
from unittest.mock import patch


class BackendTests(unittest.TestCase):
    def test_wayland_is_an_explicit_unsupported_state(self):
        self.assertIsNotNone(
            importlib.util.find_spec("activity_app.backends"), "Native capture adapter is missing"
        )
        from activity_app.backends import BackendUnavailable, native_backend

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":99"}, clear=True):
            with self.assertRaisesRegex(BackendUnavailable, "Wayland"):
                native_backend(platform="linux")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(BackendUnavailable, "X11"):
                native_backend(platform="linux")
        with self.assertRaisesRegex(BackendUnavailable, "Windows.*X11"):
            native_backend(platform="darwin")


if __name__ == "__main__":
    unittest.main()
