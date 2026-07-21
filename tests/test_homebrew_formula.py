import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "prepare_homebrew_formula.py"

spec = importlib.util.spec_from_file_location("prepare_homebrew_formula", SCRIPT_PATH)
prepare_homebrew_formula = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(prepare_homebrew_formula)


class HomebrewFormulaPrepTests(unittest.TestCase):
    def test_update_formula_content_replaces_url_and_sha256(self):
        original = (
            'class AdvaiCli < Formula\n'
            '  url "https://example.com/old.tar.gz"\n'
            '  sha256 "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
            "end\n"
        )

        updated = prepare_homebrew_formula.update_formula_content(
            original,
            url="https://files.pythonhosted.org/packages/demo/advai_cli-1.0.10.tar.gz",
            sha256="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        )

        self.assertIn(
            'url "https://files.pythonhosted.org/packages/demo/advai_cli-1.0.10.tar.gz"',
            updated,
        )
        self.assertIn(
            'sha256 "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
            updated,
        )
        self.assertNotIn("old.tar.gz", updated)

    def test_write_outputs_creates_expected_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            prepare_homebrew_formula.write_outputs(
                output_dir,
                {
                    "version": "1.0.10",
                    "url": "https://files.pythonhosted.org/packages/demo/advai_cli-1.0.10.tar.gz",
                    "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    "filename": "advai_cli-1.0.10.tar.gz",
                },
                'class AdvaiCli < Formula\n  url "https://example.com"\nend\n',
            )

            self.assertTrue((output_dir / "advai-cli.rb").exists())
            self.assertTrue((output_dir / "homebrew-core-update.json").exists())
            self.assertTrue((output_dir / "homebrew-core-update.md").exists())

            markdown = (output_dir / "homebrew-core-update.md").read_text(encoding="utf-8")
            self.assertIn("homebrew-core update for advai-cli 1.0.10", markdown)


if __name__ == "__main__":
    unittest.main()
