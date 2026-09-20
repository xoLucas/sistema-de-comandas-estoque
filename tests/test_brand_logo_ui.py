from pathlib import Path
import unittest

from jinja2 import Environment, FileSystemLoader

from app.core.seed import SEED_SETTINGS


TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


class BrandLogoSettingsTests(unittest.TestCase):
    def test_seed_settings_default_to_logo_toggle(self) -> None:
        seed_by_key = {setting["key"]: setting for setting in SEED_SETTINGS}
        for key in ("login_show_logo", "mesas_show_logo"):
            self.assertIn(key, seed_by_key)
            self.assertEqual(seed_by_key[key]["value"], "true")
            self.assertEqual(seed_by_key[key]["type"], "boolean")


class BrandLogoRenderingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

    def _render(self, template: str, **context) -> str:
        base = {"store_name": "Lads", "web_logo_url": "/static/logo.svg"}
        base.update(context)
        return self.env.get_template(template).render(**base)

    def test_login_shows_logo_and_hides_icon_when_enabled(self) -> None:
        html = self._render("login.html", login_show_logo=True)
        self.assertIn("login-brand-logo", html)
        self.assertIn('src="/static/logo.svg"', html)
        self.assertNotIn("bi-shop-window", html)
        self.assertNotIn("<h1>", html)

    def test_login_shows_text_when_disabled(self) -> None:
        html = self._render("login.html", login_show_logo=False)
        self.assertNotIn("brand-logo", html)
        self.assertIn("bi-shop-window", html)
        self.assertIn("<h1>Lads</h1>", html)

    def test_login_falls_back_to_text_without_logo_file(self) -> None:
        html = self._render("login.html", login_show_logo=True, web_logo_url=None)
        self.assertNotIn("brand-logo", html)
        self.assertIn("<h1>Lads</h1>", html)

    def test_mesas_header_shows_logo_when_enabled(self) -> None:
        html = self._render("index.html", mesas_show_logo=True)
        self.assertIn("header-brand-logo", html)
        self.assertNotIn("<h1>", html)

    def test_mesas_header_shows_text_when_disabled(self) -> None:
        html = self._render("index.html", mesas_show_logo=False)
        self.assertNotIn("brand-logo", html)
        self.assertIn("<h1>Lads</h1>", html)


if __name__ == "__main__":
    unittest.main()
