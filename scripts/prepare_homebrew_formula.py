#!/usr/bin/env python3
"""Prepare Homebrew formula updates from a published PyPI release."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FORMULA_PATH = REPO_ROOT / "Formula" / "advai-cli.rb"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "artifacts" / "homebrew-core"

URL_LINE_RE = re.compile(r'^(?P<indent>\s*)url\s+"(?P<value>[^"]+)"\s*$')
SHA_LINE_RE = re.compile(r'^(?P<indent>\s*)sha256\s+"(?P<value>[0-9a-f]+)"\s*$')


def fetch_pypi_sdist(version: str) -> dict[str, str]:
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/advai-cli/{version}/json", timeout=30
    ) as response:
        payload = json.load(response)

    sdist = next(item for item in payload["urls"] if item["packagetype"] == "sdist")
    return {
        "version": version,
        "url": sdist["url"],
        "sha256": sdist["digests"]["sha256"],
        "filename": sdist["filename"],
    }


def update_formula_content(content: str, *, url: str, sha256: str) -> str:
    updated_lines: list[str] = []
    replaced_url = False
    replaced_sha = False

    for line in content.splitlines():
        url_match = URL_LINE_RE.match(line)
        if url_match and not replaced_url:
            updated_lines.append(f'{url_match.group("indent")}url "{url}"')
            replaced_url = True
            continue

        sha_match = SHA_LINE_RE.match(line)
        if sha_match and not replaced_sha:
            updated_lines.append(f'{sha_match.group("indent")}sha256 "{sha256}"')
            replaced_sha = True
            continue

        updated_lines.append(line)

    if not replaced_url or not replaced_sha:
        raise RuntimeError("Unable to update Formula/advai-cli.rb url and sha256 fields")

    return "\n".join(updated_lines) + "\n"


def write_outputs(output_dir: Path, sdist: dict[str, str], formula_content: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "package": "advai-cli",
        "version": sdist["version"],
        "pypi_sdist_url": sdist["url"],
        "pypi_sdist_sha256": sdist["sha256"],
        "formula_path": "Formula/advai-cli.rb",
        "formula_filename": "advai-cli.rb",
    }
    (output_dir / "homebrew-core-update.json").write_text(
        json.dumps(metadata, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "advai-cli.rb").write_text(formula_content, encoding="utf-8")
    (output_dir / "homebrew-core-update.md").write_text(
        render_markdown(metadata),
        encoding="utf-8",
    )


def render_markdown(metadata: dict[str, str]) -> str:
    version = metadata["version"]
    url = metadata["pypi_sdist_url"]
    sha256 = metadata["pypi_sdist_sha256"]
    return f"""# homebrew-core update for advai-cli {version}

## Release metadata

- Version: `{version}`
- PyPI sdist URL: `{url}`
- PyPI sdist SHA256: `{sha256}`

## Suggested workflow

1. Update `Formula/a/advai-cli.rb` in your `homebrew-core` checkout with the bundled formula from this artifact.
2. Run:

```bash
brew install --build-from-source ./Formula/a/advai-cli.rb
brew test advai-cli
brew audit --strict advai-cli
```

3. Open or update the `homebrew-core` PR with the refreshed formula.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare local Formula and homebrew-core PR artifacts from PyPI metadata."
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Published advai-cli version to fetch from PyPI.",
    )
    parser.add_argument(
        "--formula-path",
        type=Path,
        default=FORMULA_PATH,
        help="Path to the local Homebrew formula to update.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated homebrew-core update artifacts.",
    )
    parser.add_argument(
        "--write-formula",
        action="store_true",
        help="Overwrite the local formula file with the updated URL and SHA256.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    sdist = fetch_pypi_sdist(args.version)
    original_formula = args.formula_path.read_text(encoding="utf-8")
    updated_formula = update_formula_content(
        original_formula,
        url=sdist["url"],
        sha256=sdist["sha256"],
    )

    if args.write_formula:
        args.formula_path.write_text(updated_formula, encoding="utf-8")

    write_outputs(args.output_dir, sdist, updated_formula)

    print(f"Prepared Homebrew formula assets for advai-cli {args.version}")
    print(f"PyPI sdist URL: {sdist['url']}")
    print(f"PyPI sdist SHA256: {sdist['sha256']}")
    print(f"Artifact directory: {args.output_dir}")
    if args.write_formula:
        print(f"Updated local formula: {args.formula_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
