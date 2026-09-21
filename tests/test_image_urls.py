"""Tests for _fix_relative_image_urls in sensor.py."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# The sensor module imports homeassistant and smartschool. Those aren't needed here
# to test just _fix_relative_image_urls, so we set up minimal stub modules so that
# "import sensor" doesn't fail on missing dependencies.
_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PACKAGE_ROOT.parent))


def _stub_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules.setdefault(name, module)
    return module


_stub_module("homeassistant")
_stub_module("homeassistant.components")
_stub_module("homeassistant.components.sensor", SensorEntity=object)
_stub_module("homeassistant.helpers")
_stub_module("homeassistant.helpers.entity_registry")
_stub_module(
    "homeassistant.util",
    dt=types.SimpleNamespace(DEFAULT_TIME_ZONE=None, now=lambda: None, utcnow=lambda: None),
    slugify=lambda value: str(value).lower().replace(" ", "_"),
)
_stub_module(
    "smartschool",
    Attachments=object,
    BoxType=object,
    MarkMessageUnread=object,
    Message=object,
    MessageHeaders=object,
)

# sensor.py does "from .const import DOMAIN", so we load it as a submodule of a
# (stub) package instead of as a standalone script, to keep the relative import working.
import importlib.util

_pkg = types.ModuleType("custom_components.smartschool")
_pkg.__path__ = [str(_PACKAGE_ROOT)]
sys.modules.setdefault("custom_components", types.ModuleType("custom_components"))
sys.modules["custom_components"].__path__ = [str(_PACKAGE_ROOT.parent)]
sys.modules["custom_components.smartschool"] = _pkg
_stub_module("custom_components.smartschool.const", DOMAIN="smartschool", SCAN_INTERVAL=None)

_spec = importlib.util.spec_from_file_location(
    "custom_components.smartschool.sensor", _PACKAGE_ROOT / "sensor.py"
)
sensor = importlib.util.module_from_spec(_spec)
sys.modules["custom_components.smartschool.sensor"] = sensor
_spec.loader.exec_module(sensor)


class FixRelativeImageUrlsTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.creds.main_url = "myschool.smartschool.be"

    def test_relative_path_with_leading_slash_is_rewritten(self):
        body = '<p>See <img src="/public/myschool/Images/foo.png" border="0"></p>'
        result = sensor._fix_relative_image_urls(body, self.session)
        self.assertIn('src="https://myschool.smartschool.be/public/myschool/Images/foo.png"', result)

    def test_relative_path_without_leading_slash_is_rewritten(self):
        body = "<img src='public/myschool/Images/foo.png'>"
        result = sensor._fix_relative_image_urls(body, self.session)
        self.assertIn("src='https://myschool.smartschool.be/public/myschool/Images/foo.png'", result)

    def test_absolute_http_url_is_untouched(self):
        body = '<img src="http://example.com/foo.png">'
        result = sensor._fix_relative_image_urls(body, self.session)
        self.assertEqual(body, result)

    def test_absolute_https_url_is_untouched(self):
        body = '<img src="https://userpicture10.smartschool.be/User/foo.png">'
        result = sensor._fix_relative_image_urls(body, self.session)
        self.assertEqual(body, result)

    def test_data_uri_is_untouched(self):
        body = '<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUg==">'
        result = sensor._fix_relative_image_urls(body, self.session)
        self.assertEqual(body, result)

    def test_empty_body_is_returned_unchanged(self):
        self.assertEqual(sensor._fix_relative_image_urls("", self.session), "")
        self.assertIsNone(sensor._fix_relative_image_urls(None, self.session))


if __name__ == "__main__":
    unittest.main()
