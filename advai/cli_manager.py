import json
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from functools import lru_cache

from advai import __version__

PACKAGE_NAME = "advai-cli"
BREW_FORMULA = "advai-cli"
SUPPORTED_MANAGERS = ("pip", "npm", "brew")
CLIS_DIR = os.path.expanduser("~/.advai/clis")
GITHUB_REPO_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
GITHUB_TREE_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/tree/(?P<ref>.+?)/?$"
)


def _normalize_path(value: str) -> str:
    if not value:
        return ""
    return os.path.realpath(os.path.expanduser(value))


def looks_like_github_url(value: str) -> bool:
    candidate = str(value or "").strip()
    return bool(GITHUB_REPO_PATTERN.match(candidate) or GITHUB_TREE_PATTERN.match(candidate))


def _parse_github_spec(spec: str) -> dict | None:
    value = str(spec or "").strip()
    if not value:
        return None

    tree_match = GITHUB_TREE_PATTERN.match(value)
    if tree_match:
        data = tree_match.groupdict()
        return {
            "owner": data["owner"],
            "repo": data["repo"],
            "ref": data["ref"],
            "url": f"https://github.com/{data['owner']}/{data['repo']}",
            "install_spec": value,
        }

    repo_match = GITHUB_REPO_PATTERN.match(value)
    if repo_match:
        data = repo_match.groupdict()
        return {
            "owner": data["owner"],
            "repo": data["repo"],
            "ref": None,
            "url": f"https://github.com/{data['owner']}/{data['repo']}",
            "install_spec": value,
        }
    return None


def _json_request(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "advai-cli",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Failed to fetch GitHub metadata: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to reach GitHub: {exc.reason}") from exc


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "advai-cli"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Failed to download GitHub archive: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Unable to download GitHub archive: {exc.reason}") from exc


def _resolve_github_ref(parsed: dict) -> str:
    if parsed.get("ref"):
        return parsed["ref"]
    repo_api = f"https://api.github.com/repos/{parsed['owner']}/{parsed['repo']}"
    data = _json_request(repo_api)
    default_branch = str(data.get("default_branch") or "").strip()
    if not default_branch:
        raise RuntimeError("GitHub repository has no default branch")
    return default_branch


def _extract_github_repo(parsed: dict) -> tuple[str, dict]:
    ref = _resolve_github_ref(parsed)
    archive_url = (
        f"https://api.github.com/repos/{parsed['owner']}/{parsed['repo']}/zipball/{ref}"
    )
    archive_bytes = _download_bytes(archive_url)
    temp_dir = tempfile.mkdtemp(prefix="advai-cli-")

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            archive.extractall(temp_dir)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("GitHub archive is not a valid zip file") from exc

    entries = [
        os.path.join(temp_dir, name)
        for name in os.listdir(temp_dir)
        if not name.startswith(".")
    ]
    repo_root = next((path for path in entries if os.path.isdir(path)), None)
    if repo_root is None:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError("GitHub archive did not contain a repository directory")

    source = {
        "type": "github",
        "url": parsed["url"],
        "owner": parsed["owner"],
        "repo": parsed["repo"],
        "ref": ref,
        "install_spec": parsed["install_spec"],
        "archive_url": archive_url,
    }
    return repo_root, source


def _load_json_if_exists(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _cli_meta_path(cli_name: str) -> str:
    return os.path.join(CLIS_DIR, cli_name, "cli.json")


def _list_repo_clis(repo_root: str) -> list[str]:
    clis_root = os.path.join(repo_root, "clis")
    if not os.path.isdir(clis_root):
        raise RuntimeError("GitHub repository does not contain a root-level clis directory")
    return sorted(
        name
        for name in os.listdir(clis_root)
        if os.path.isdir(os.path.join(clis_root, name)) and not name.startswith(".")
    )


def list_github_repo_clis(spec: str) -> list[str]:
    parsed = _parse_github_spec(spec)
    if parsed is None:
        raise RuntimeError("Unsupported GitHub URL")
    repo_root, _source = _extract_github_repo(parsed)
    cleanup_root = os.path.dirname(repo_root)
    try:
        return _list_repo_clis(repo_root)
    finally:
        shutil.rmtree(cleanup_root, ignore_errors=True)


def _build_register_command_from_manifest(cli_dir: str) -> tuple[str, list, dict]:
    manifest = _load_json_if_exists(os.path.join(cli_dir, "cli.json"))
    cli_dir_name = os.path.basename(cli_dir)
    cli_name = str(manifest.get("name") or cli_dir_name).strip()
    if not cli_name:
        cli_name = cli_dir_name

    binary = str(manifest.get("binary") or cli_name).strip()
    install_command = str(manifest.get("install") or "").strip()
    description = str(manifest.get("description") or "").strip()

    command = ["opencli", "external", "register", cli_name]
    if binary and binary != cli_name:
        command.extend(["--binary", binary])
    if install_command:
        command.extend(["--install", install_command])
    if description:
        command.extend(["--desc", description])

    metadata = {
        "name": cli_name,
        "binary": binary,
        "install": install_command,
        "description": description,
        "homepage": str(manifest.get("homepage") or "").strip(),
        "tags": manifest.get("tags") or [],
    }
    return cli_name, command, metadata


def install_github_clis(spec: str, selected_clis: list[str] | None = None) -> list[dict]:
    parsed = _parse_github_spec(spec)
    if parsed is None:
        raise RuntimeError("Unsupported GitHub URL")

    repo_root, source = _extract_github_repo(parsed)
    cleanup_root = os.path.dirname(repo_root)
    try:
        available_clis = _list_repo_clis(repo_root)
        if not available_clis:
            raise RuntimeError("GitHub repository clis directory is empty")

        if selected_clis:
            unknown = [name for name in selected_clis if name not in available_clis]
            if unknown:
                available = ", ".join(available_clis)
                missing = ", ".join(unknown)
                raise RuntimeError(
                    f"CLI '{missing}' not found in repository clis directory. "
                    f"Available CLIs: {available}"
                )
            targets = selected_clis
        else:
            targets = available_clis

        installed = []
        clis_root = os.path.join(repo_root, "clis")
        os.makedirs(CLIS_DIR, exist_ok=True)
        for dir_name in targets:
            cli_dir = os.path.join(clis_root, dir_name)
            cli_name, command, metadata = _build_register_command_from_manifest(cli_dir)
            result = run_manager_command(command)
            if result["returncode"] != 0:
                message = result["stderr"] or result["stdout"] or "opencli register failed"
                raise RuntimeError(message)

            meta_dir = os.path.join(CLIS_DIR, cli_name)
            os.makedirs(meta_dir, exist_ok=True)
            with open(_cli_meta_path(cli_name), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        **metadata,
                        "source": {
                            **source,
                            "cli": dir_name,
                        },
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
            installed.append(metadata)
        return installed
    finally:
        shutil.rmtree(cleanup_root, ignore_errors=True)


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


def build_external_cli_update_command(cli_name: str) -> list:
    return ["opencli", "external", "update", cli_name]


def build_external_cli_uninstall_command(cli_name: str) -> list:
    return ["opencli", "external", "uninstall", cli_name]


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
