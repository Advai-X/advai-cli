import json
import os
import re

CONFIG_DIR = os.path.expanduser("~/.advai")
PLATFORM_CONFIG_PATH = os.path.join(CONFIG_DIR, "skill_platforms.json")
KEY_PATTERN = re.compile(r"^[a-z0-9_]+$")

BUILTIN_PLATFORMS = [
    {
        "key": "cursor",
        "display_name": "Cursor",
        "category": "coding",
        "relative_skills_dir": ".cursor/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "claude_code",
        "display_name": "Claude Code",
        "category": "coding",
        "relative_skills_dir": ".claude/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "omp_agent",
        "display_name": "OMP Agent",
        "category": "coding",
        "relative_skills_dir": ".omp/agent/skills",
        "project_relative_skills_dir": ".omp/skills",
    },
    {
        "key": "codex",
        "display_name": "Codex",
        "category": "coding",
        "relative_skills_dir": ".codex/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "grok",
        "display_name": "Grok",
        "category": "coding",
        "relative_skills_dir": ".grok/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "opencode",
        "display_name": "OpenCode",
        "category": "coding",
        "relative_skills_dir": ".config/opencode/skills",
        "project_relative_skills_dir": ".opencode/skills",
    },
    {
        "key": "antigravity",
        "display_name": "Antigravity",
        "category": "coding",
        "relative_skills_dir": ".gemini/antigravity/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "amp",
        "display_name": "Amp",
        "category": "coding",
        "relative_skills_dir": ".config/agents/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "kilo_code",
        "display_name": "Kilo Code",
        "category": "coding",
        "relative_skills_dir": ".kilocode/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "roo_code",
        "display_name": "Roo Code",
        "category": "coding",
        "relative_skills_dir": ".roo/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "goose",
        "display_name": "Goose",
        "category": "coding",
        "relative_skills_dir": ".config/goose/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "gemini_cli",
        "display_name": "Gemini CLI",
        "category": "coding",
        "relative_skills_dir": ".gemini/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "github_copilot",
        "display_name": "GitHub Copilot",
        "category": "coding",
        "relative_skills_dir": ".copilot/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "openclaw",
        "display_name": "OpenClaw",
        "category": "lobster",
        "relative_skills_dir": ".openclaw/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "droid",
        "display_name": "Droid",
        "category": "coding",
        "relative_skills_dir": ".factory/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "windsurf",
        "display_name": "Windsurf",
        "category": "coding",
        "relative_skills_dir": ".codeium/windsurf/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "trae",
        "display_name": "TRAE IDE",
        "category": "coding",
        "relative_skills_dir": ".trae/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "cline",
        "display_name": "Cline",
        "category": "coding",
        "relative_skills_dir": ".agents/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "deepagents",
        "display_name": "Deep Agents",
        "category": "coding",
        "relative_skills_dir": ".deepagents/agent/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "firebender",
        "display_name": "Firebender",
        "category": "coding",
        "relative_skills_dir": ".firebender/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "kimi",
        "display_name": "Kimi Code CLI",
        "category": "coding",
        "relative_skills_dir": ".config/agents/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "replit",
        "display_name": "Replit",
        "category": "coding",
        "relative_skills_dir": ".config/agents/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "warp",
        "display_name": "Warp",
        "category": "coding",
        "relative_skills_dir": ".agents/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "augment",
        "display_name": "Augment",
        "category": "coding",
        "relative_skills_dir": ".augment/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "bob",
        "display_name": "IBM Bob",
        "category": "coding",
        "relative_skills_dir": ".bob/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "codebuddy",
        "display_name": "CodeBuddy",
        "category": "coding",
        "relative_skills_dir": ".codebuddy/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "command_code",
        "display_name": "Command Code",
        "category": "coding",
        "relative_skills_dir": ".commandcode/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "continue",
        "display_name": "Continue",
        "category": "coding",
        "relative_skills_dir": ".continue/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "cortex",
        "display_name": "Cortex Code",
        "category": "coding",
        "relative_skills_dir": ".snowflake/cortex/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "crush",
        "display_name": "Crush",
        "category": "coding",
        "relative_skills_dir": ".config/crush/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "iflow",
        "display_name": "iFlow CLI",
        "category": "coding",
        "relative_skills_dir": ".iflow/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "junie",
        "display_name": "Junie",
        "category": "coding",
        "relative_skills_dir": ".junie/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "kiro",
        "display_name": "Kiro CLI",
        "category": "coding",
        "relative_skills_dir": ".kiro/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "kode",
        "display_name": "Kode",
        "category": "coding",
        "relative_skills_dir": ".kode/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "mcpjam",
        "display_name": "MCPJam",
        "category": "coding",
        "relative_skills_dir": ".mcpjam/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "mistral_vibe",
        "display_name": "Mistral Vibe",
        "category": "coding",
        "relative_skills_dir": ".vibe/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "mux",
        "display_name": "Mux",
        "category": "coding",
        "relative_skills_dir": ".mux/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "neovate",
        "display_name": "Neovate",
        "category": "coding",
        "relative_skills_dir": ".neovate/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "openhands",
        "display_name": "OpenHands",
        "category": "coding",
        "relative_skills_dir": ".openhands/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "pi",
        "display_name": "Pi",
        "category": "coding",
        "relative_skills_dir": ".pi/agent/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "pochi",
        "display_name": "Pochi",
        "category": "coding",
        "relative_skills_dir": ".pochi/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "qoder",
        "display_name": "Qoder",
        "category": "coding",
        "relative_skills_dir": ".qoder/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "qwen_code",
        "display_name": "Qwen Code",
        "category": "coding",
        "relative_skills_dir": ".qwen/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "trae_cn",
        "display_name": "TRAE CN",
        "category": "coding",
        "relative_skills_dir": ".trae-cn/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "zencoder",
        "display_name": "Zencoder",
        "category": "coding",
        "relative_skills_dir": ".zencoder/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "adal",
        "display_name": "AdaL",
        "category": "coding",
        "relative_skills_dir": ".adal/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "hermes",
        "display_name": "Hermes Agent",
        "category": "lobster",
        "relative_skills_dir": ".hermes/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "qclaw",
        "display_name": "QClaw",
        "category": "lobster",
        "relative_skills_dir": ".qclaw/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "easyclaw",
        "display_name": "EasyClaw",
        "category": "lobster",
        "relative_skills_dir": ".easyclaw/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "autoclaw",
        "display_name": "AutoClaw",
        "category": "lobster",
        "relative_skills_dir": ".openclaw-autoclaw/skills",
        "project_relative_skills_dir": None,
    },
    {
        "key": "workbuddy",
        "display_name": "WorkBuddy",
        "category": "lobster",
        "relative_skills_dir": ".workbuddy/skills-marketplace/skills",
        "project_relative_skills_dir": None,
    },
]


def _platform_config_template() -> dict:
    return {
        "custom_platforms": [],
        "path_overrides": {},
        "project_path_overrides": {},
    }


def _load_platform_config() -> dict:
    if not os.path.isfile(PLATFORM_CONFIG_PATH):
        return _platform_config_template()
    with open(PLATFORM_CONFIG_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    merged = _platform_config_template()
    if isinstance(data, dict):
        for key, value in data.items():
            if key in merged and isinstance(value, type(merged[key])):
                merged[key] = value
    return merged


def _save_platform_config(config: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PLATFORM_CONFIG_PATH, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)


def _builtin_platform_index() -> dict:
    return {platform["key"]: dict(platform) for platform in BUILTIN_PLATFORMS}


def _normalize_platform_key(key: str) -> str:
    candidate = str(key or "").strip().lower().replace("-", "_")
    if not KEY_PATTERN.match(candidate):
        raise ValueError("Platform key must match: [a-z0-9_]+")
    return candidate


def _normalize_category(category: str) -> str:
    candidate = str(category or "").strip().lower()
    if candidate not in {"coding", "lobster", "custom"}:
        raise ValueError("Platform category must be one of: coding, lobster, custom")
    return candidate


def _normalize_project_path(project_relative_skills_dir: str | None) -> str | None:
    if project_relative_skills_dir is None:
        return None
    value = str(project_relative_skills_dir).strip()
    if not value:
        return None
    return value


def list_skill_platforms() -> list[dict]:
    config = _load_platform_config()
    index = _builtin_platform_index()

    for key, override in config["path_overrides"].items():
        if key in index and str(override).strip():
            index[key]["skills_dir"] = str(override).strip()

    for key, override in config["project_path_overrides"].items():
        if key in index:
            index[key]["project_relative_skills_dir"] = _normalize_project_path(override)

    for platform in config["custom_platforms"]:
        key = platform.get("key")
        if not key or key in index:
            continue
        index[key] = {
            "key": key,
            "display_name": platform.get("display_name") or key,
            "category": platform.get("category") or "custom",
            "relative_skills_dir": None,
            "project_relative_skills_dir": _normalize_project_path(
                platform.get("project_relative_skills_dir")
            ),
            "skills_dir": str(platform.get("skills_dir") or "").strip() or None,
            "is_custom": True,
        }

    platforms = []
    for platform in index.values():
        item = dict(platform)
        item.setdefault("is_custom", False)
        item.setdefault("skills_dir", None)
        item.setdefault("relative_skills_dir", None)
        item.setdefault("project_relative_skills_dir", None)
        platforms.append(item)

    return sorted(
        platforms,
        key=lambda item: (
            item.get("category") or "",
            (item.get("display_name") or item["key"]).lower(),
        ),
    )


def get_skill_platform(platform_key: str) -> dict | None:
    key = _normalize_platform_key(platform_key)
    for platform in list_skill_platforms():
        if platform["key"] == key:
            return platform
    return None


def resolve_platform_target(platform_key: str, project_dir: str | None = None) -> dict:
    platform = get_skill_platform(platform_key)
    if platform is None:
        raise KeyError(f"Unknown platform '{platform_key}'")

    normalized_project_dir = None
    if project_dir and platform.get("project_relative_skills_dir"):
        normalized_project_dir = os.path.abspath(os.path.expanduser(project_dir))
        skills_dir = os.path.join(
            normalized_project_dir, platform["project_relative_skills_dir"]
        )
    else:
        explicit = platform.get("skills_dir")
        if explicit:
            skills_dir = os.path.expanduser(explicit)
        else:
            skills_dir = os.path.join(
                os.path.expanduser("~"), platform["relative_skills_dir"]
            )

    return {
        "platform": platform,
        "skills_dir": os.path.abspath(skills_dir),
        "project_dir": normalized_project_dir,
    }


def add_custom_platform(
    key: str,
    display_name: str,
    skills_dir: str,
    category: str = "custom",
    project_relative_skills_dir: str | None = None,
) -> dict:
    normalized_key = _normalize_platform_key(key)
    if get_skill_platform(normalized_key) is not None:
        raise ValueError(f"Platform '{normalized_key}' already exists")

    normalized_display_name = str(display_name or "").strip()
    if not normalized_display_name:
        raise ValueError("Platform display name is required")

    normalized_skills_dir = str(skills_dir or "").strip()
    if not normalized_skills_dir:
        raise ValueError("Platform skills path is required")

    config = _load_platform_config()
    config["custom_platforms"].append(
        {
            "key": normalized_key,
            "display_name": normalized_display_name,
            "skills_dir": normalized_skills_dir,
            "project_relative_skills_dir": _normalize_project_path(
                project_relative_skills_dir
            ),
            "category": _normalize_category(category),
        }
    )
    _save_platform_config(config)
    return get_skill_platform(normalized_key)


def remove_custom_platform(key: str) -> None:
    normalized_key = _normalize_platform_key(key)
    config = _load_platform_config()
    original_count = len(config["custom_platforms"])
    config["custom_platforms"] = [
        platform
        for platform in config["custom_platforms"]
        if platform.get("key") != normalized_key
    ]
    if len(config["custom_platforms"]) == original_count:
        raise KeyError(f"Custom platform '{normalized_key}' was not found")
    _save_platform_config(config)


def set_platform_override(
    key: str,
    skills_dir: str | None = None,
    project_relative_skills_dir: str | None = None,
) -> dict:
    normalized_key = _normalize_platform_key(key)
    platform = get_skill_platform(normalized_key)
    if platform is None:
        raise KeyError(f"Unknown platform '{normalized_key}'")

    config = _load_platform_config()
    updated = False

    if platform.get("is_custom"):
        for item in config["custom_platforms"]:
            if item.get("key") != normalized_key:
                continue
            if skills_dir is not None:
                value = str(skills_dir).strip()
                if not value:
                    raise ValueError("Platform skills path cannot be empty")
                item["skills_dir"] = value
                updated = True
            if project_relative_skills_dir is not None:
                item["project_relative_skills_dir"] = _normalize_project_path(
                    project_relative_skills_dir
                )
                updated = True
            break
    else:
        if skills_dir is not None:
            value = str(skills_dir).strip()
            if not value:
                raise ValueError("Platform skills path cannot be empty")
            config["path_overrides"][normalized_key] = value
            updated = True
        if project_relative_skills_dir is not None:
            normalized_project_path = _normalize_project_path(project_relative_skills_dir)
            if normalized_project_path is None:
                config["project_path_overrides"].pop(normalized_key, None)
            else:
                config["project_path_overrides"][normalized_key] = normalized_project_path
            updated = True

    if not updated:
        raise ValueError("No platform override values were provided")

    _save_platform_config(config)
    return get_skill_platform(normalized_key)


def clear_platform_override(
    key: str,
    clear_skills_dir: bool = True,
    clear_project_relative_skills_dir: bool = True,
) -> dict:
    normalized_key = _normalize_platform_key(key)
    platform = get_skill_platform(normalized_key)
    if platform is None:
        raise KeyError(f"Unknown platform '{normalized_key}'")
    if platform.get("is_custom"):
        raise ValueError("Custom platforms use 'platform remove' or 'platform override'")

    config = _load_platform_config()
    if clear_skills_dir:
        config["path_overrides"].pop(normalized_key, None)
    if clear_project_relative_skills_dir:
        config["project_path_overrides"].pop(normalized_key, None)
    _save_platform_config(config)
    return get_skill_platform(normalized_key)
