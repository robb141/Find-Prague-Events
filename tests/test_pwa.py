import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PwaTests(unittest.TestCase):
    def test_manifest_has_installable_settings_and_icons(self):
        manifest = json.loads((ROOT / "manifest.webmanifest").read_text())

        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue(manifest["start_url"].startswith("./"))
        self.assertTrue(manifest["scope"].startswith("./"))

        sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)

        for icon in manifest["icons"]:
            self.assertTrue((ROOT / icon["src"]).is_file(), icon["src"])

    def test_app_shell_files_exist(self):
        for relative_path in (
            "index.html",
            "styles.css",
            "script.js",
            "data.js",
            "manifest.webmanifest",
            "sw.js",
        ):
            self.assertTrue((ROOT / relative_path).is_file(), relative_path)

    def test_service_worker_is_registered_and_references_current_cache(self):
        index = (ROOT / "index.html").read_text()
        script = (ROOT / "script.js").read_text()
        service_worker = (ROOT / "sw.js").read_text()

        self.assertIn('rel="manifest"', index)
        self.assertIn('navigator.serviceWorker.register("./sw.js")', script)
        self.assertIn('const CACHE_NAME = "find-prague-events-v4"', service_worker)


if __name__ == "__main__":
    unittest.main()
