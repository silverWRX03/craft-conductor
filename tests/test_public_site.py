"""Basic public-site safety, packaging and preservation checks.

Run after: python tools/build_public_site.py --output _site --version development
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "_site"


class PublicSiteBuildTests(unittest.TestCase):
    def test_site_and_important_existing_routes(self):
        for path in ("index.html", "home.js", "css/home.css",
                     "testing/index.html", "testing/data", "join/index.html",
                     "googlef2c4a8b5e575e76a.html"):
            self.assertTrue((SITE / path).exists(), path)

    def test_real_frontend_packaged(self):
        for path in ("demo/index.html", "demo/app.js", "demo/style.css",
                     "demo/craft-conductor-theme.css", "demo/demo-runtime.js",
                     "demo/demo-runtime.css", "demo/coverage.json", "demo/release.json",
                     "demo/phone-qr.svg"):
            self.assertTrue((SITE / path).is_file(), path)
        page = (SITE / "demo/index.html").read_text(encoding="utf-8")
        self.assertIn('src="demo-runtime.js"', page)
        self.assertIn('src="app.js"', page)
        self.assertNotIn('src="/app.js"', page)
        self.assertNotIn('rel="manifest"', page)

    def test_demo_security(self):
        app = (SITE / "demo/app.js").read_text(encoding="utf-8")
        runtime = (SITE / "demo/demo-runtime.js").read_text(encoding="utf-8")
        self.assertNotIn("  registerWorker();", app)
        self.assertIn('loadLanguage("./")', app)
        self.assertIn('window.fetch=', runtime)
        self.assertIn('window.XMLHttpRequest=', runtime)
        self.assertIn("External fetch disabled", runtime)

    def test_coverage_version(self):
        manifest = json.loads((SITE / "demo/coverage.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(manifest["server_routes"]), 9)
        release = json.loads((SITE / "demo/release.json").read_text(encoding="utf-8"))
        self.assertEqual(release["application_version"] if "application_version" in release else
                         release["version"], manifest["application_version"])


if __name__ == "__main__":
    unittest.main()
