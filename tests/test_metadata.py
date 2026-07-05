import json
import unittest
from pathlib import Path

from advai import __version__


REPO_ROOT = Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def test_python_and_npm_versions_stay_in_sync(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))

        pyproject_version_line = next(
            line for line in pyproject.splitlines() if line.startswith('version = "')
        )
        pyproject_version = pyproject_version_line.split('"')[1]

        self.assertEqual(pyproject_version, __version__)
        self.assertEqual(package["version"], __version__)

    def test_npm_package_includes_private_python_installer(self):
        package = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))
        files = set(package["files"])

        self.assertIn("advai/cli.py", files)
        self.assertIn("advai/browser_bridge.py", files)
        self.assertIn("advai/kb.py", files)
        self.assertIn("bin/advai.js", files)
        self.assertIn("bin/install-python.js", files)


if __name__ == "__main__":
    unittest.main()
