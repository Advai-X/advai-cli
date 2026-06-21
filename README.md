# advai-cli — Cross-platform AI Skill Manager

A Python CLI that lets you install / uninstall AI Skills.

- **Platforms**: macOS / Linux / Windows
- **Installation**: pip, npm, or one-line script
- **Commands**: install, uninstall, list, update, info

---

## Quick Start

```bash
# pip (recommended)
pip install advai-cli

# install after installation, the `advai` command is ready to use

Advai --help
advai --version
advai install <skill-name>
advai uninstall <skill-name>
```

---

## Project Structure

```
advai/              # core CLI (Python)
  __init__.py
  cli.py            # entry point (click-based)
  skills.py          # Skill install / uninstall / metadata logic
Formula/advai.rb    # Homebrew formula
bin/advai.js        # npm entry point bridge
install.sh          # one-click installer script
pyproject.toml    # PyPI build configuration
package.json        # npm package configuration
```

---

## Local Development

```bash
# run from source
python3 -m advai.cli --help
```

---

## License

MIT
