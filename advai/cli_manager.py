import os
import shutil
import subprocess
import sys
import json
from functools import lru_cache

from advai import __version__

PACKAGE_NAME = "advai-cli"
BREW_FORMULA = "advai-cli"
SUPPORTED_MANAGERS = ("pip", "npm", "brew")


def _normalize_path(value: str) -> str:
    if not value:
        return ""
    return os.path.realpath(os.path.expanduser(value))


def detect_install_method() -> str:
    argv0 = _normalize_path(sys.argv[0])
    module_path = _normalize_path(__file__)
    combined = f"{argv0} {module_path}".lower()

    if "cellar" in combined or "homebrew" in combined:
        return "brew"
    if "node_modules" in combined or argv0.endswith(".js"):
        return "npm"
    if "site-packages" in combined or "dist-packages" in combined:
        return "pip"
    return "source"


def available_managers() -> dict:
    return {
        "pip": bool(sys.executable),
        "npm": shutil.which("npm") is not None,
        "brew": shutil.which("brew") is not None,
    }


def cli_info() -> dict:
    return {
        "name": PACKAGE_NAME,
        "version": __version__,
        "install_method": detect_install_method(),
        "python": sys.executable,
        "entry": _normalize_path(sys.argv[0]),
        "module": _normalize_path(__file__),
        "skills_dir": os.path.expanduser("~/.advai/skills"),
        "available_managers": available_managers(),
    }


def list_cli_targets() -> list:
    info = cli_info()
    detected = info["install_method"]
    managers = info["available_managers"]
    items = []
    for name, available in managers.items():
        status = "available" if available else "unavailable"
        if name == detected:
            status = f"{status}, detected"
        items.append({"name": name, "status": status})
    if detected not in managers:
        items.append({"name": detected, "status": "detected"})
    return items


def opencli_available() -> bool:
    return shutil.which("opencli") is not None


@lru_cache(maxsize=1)
def _opencli_registry() -> list:
    if not opencli_available():
        return []
    result = subprocess.run(
        ["opencli", "list", "-f", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to query opencli registry")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse opencli registry output") from exc


@lru_cache(maxsize=1)
def _opencli_external_registry() -> list:
    if not opencli_available():
        return []
    result = subprocess.run(
        ["opencli", "external", "list", "-f", "json"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Failed to query opencli external registry")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse opencli external registry output") from exc


def list_available_clis(search: str = "") -> list:
    term = str(search or "").strip().lower()
    grouped = {}
    for item in _opencli_registry():
        site = str(item.get("site") or "").strip()
        if not site:
            continue
        if term and term not in site.lower():
            continue
        info = grouped.setdefault(
            site,
            {
                "name": site,
                "command_count": 0,
                "commands": [],
                "description": "",
            },
        )
        info["command_count"] += 1
        command_name = str(item.get("name") or "").strip()
        if command_name:
            info["commands"].append(command_name)
        if not info["description"]:
            info["description"] = str(item.get("description") or "").strip()
    return [grouped[name] for name in sorted(grouped)]


def get_available_cli_info(cli_name: str) -> dict | None:
    target = str(cli_name or "").strip()
    if not target:
        return None
    for item in list_available_clis():
        if item["name"] == target:
            return item
    return None


def list_external_clis(search: str = "") -> list:
    term = str(search or "").strip().lower()
    items = []
    for item in _opencli_external_registry():
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        if term and term not in name.lower():
            continue
        items.append(item)
    return items


def get_external_cli_info(cli_name: str) -> dict | None:
    target = str(cli_name or "").strip()
    if not target:
        return None
    for item in _opencli_external_registry():
        if str(item.get("name") or "").strip() == target:
            return item
    return None


def cli_exists(cli_name: str) -> bool:
    target = str(cli_name or "").strip()
    if not target:
        return False
    for item in _opencli_registry():
        if str(item.get("site") or "").strip() == target:
            return True
    return False


def build_cli_exec_command(cli_name: str, args: list | None = None) -> list:
    command = ["opencli", cli_name]
    if args:
        command.extend(args)
    return command


def build_external_cli_install_command(cli_name: str) -> list:
    return ["opencli", "external", "install", cli_name]


def run_passthrough_command(command: list) -> int:
    result = subprocess.run(command)
    return result.returncode


def resolve_manager(manager: str = None) -> str:
    if manager:
        return manager
    detected = detect_install_method()
    if detected in SUPPORTED_MANAGERS:
        return detected
    return "pip"


def build_install_command(manager: str, reinstall: bool = False) -> list:
    if manager == "pip":
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
        if reinstall:
            cmd.append("--force-reinstall")
        cmd.append(PACKAGE_NAME)
        return cmd
    if manager == "npm":
        return ["npm", "install", "-g", PACKAGE_NAME]
    if manager == "brew":
        if reinstall:
            return ["brew", "reinstall", BREW_FORMULA]
        return ["brew", "install", BREW_FORMULA]
    raise ValueError(f"Unsupported manager: {manager}")


def build_update_command(manager: str) -> list:
    if manager == "pip":
        return [sys.executable, "-m", "pip", "install", "--upgrade", PACKAGE_NAME]
    if manager == "npm":
        return ["npm", "install", "-g", f"{PACKAGE_NAME}@latest"]
    if manager == "brew":
        return ["brew", "upgrade", BREW_FORMULA]
    raise ValueError(f"Unsupported manager: {manager}")


def build_recommended_update_command() -> list:
    manager = resolve_manager()
    return build_update_command(manager)


def build_uninstall_command(manager: str) -> list:
    if manager == "pip":
        return [sys.executable, "-m", "pip", "uninstall", "-y", PACKAGE_NAME]
    if manager == "npm":
        return ["npm", "uninstall", "-g", PACKAGE_NAME]
    if manager == "brew":
        return ["brew", "uninstall", BREW_FORMULA]
    raise ValueError(f"Unsupported manager: {manager}")


def run_manager_command(command: list) -> dict:
    result = subprocess.run(command, capture_output=True, text=True)
    return {
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def ensure_manager_available(manager: str) -> None:
    available = available_managers()
    if not available.get(manager):
        raise RuntimeError(f"Package manager '{manager}' is not available on this system")
