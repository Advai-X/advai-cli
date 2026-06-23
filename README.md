# advai-cli

`advai-cli` is a command-line tool for managing AdvAI skills and working with external CLIs through a single `advai` entrypoint.

## Features

- Show local `advai` runtime and installation details
- Install, list, inspect, update, and uninstall local skills
- Discover installable external CLIs
- Install third-party CLIs through `advai cli install`
- Execute supported external CLIs through `advai cli <name> ...`

## Install

### PyPI

```bash
pip install advai-cli
```

### npm

```bash
npm install -g advai-cli
```

### Homebrew tap

```bash
brew install Advai-X/advai-x-cli/advai-cli
```

## Usage

```bash
advai --help
advai info
advai update
```

### Skill commands

```bash
advai skill list
advai skill info demo-skill
advai skill install demo-skill
advai skill update demo-skill
advai skill uninstall demo-skill
```

### External CLI commands

```bash
advai cli list
advai cli info demo-cli
advai cli install demo-cli --yes
```
