import json
import io
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone

SKILLS_DIR = os.path.expanduser("~/.advai/skills")
CONFIG_DIR = os.path.expanduser("~/.advai")
GITHUB_REPO_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
GITHUB_TREE_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/tree/(?P<ref>.+?)/?$"
)


def _skill_path(skill_name: str) -> str:
    return os.path.join(SKILLS_DIR, skill_name)


def _meta_path(skill_name: str) -> str:
    return os.path.join(_skill_path(skill_name), "skill.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _looks_like_github_url(value: str) -> bool:
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
    temp_dir = tempfile.mkdtemp(prefix="advai-skill-")

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


def _load_skill_metadata(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_skill_metadata(skill_name: str, metadata: dict) -> None:
    with open(_meta_path(skill_name), "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)


def _install_placeholder_skill(skill_name: str, force: bool = False) -> dict:
    path = _skill_path(skill_name)
    if os.path.exists(path) and not force:
        raise FileExistsError(skill_name)

    os.makedirs(path, exist_ok=True)
    meta = {
        "name": skill_name,
        "version": "0.1.0",
        "installed_at": _utc_now(),
        "status": "installed",
        "source": {
            "type": "local",
            "install_spec": skill_name,
        },
    }
    _write_skill_metadata(skill_name, meta)
    return meta


def _list_repo_skills(repo_root: str) -> list[str]:
    skills_root = os.path.join(repo_root, "skills")
    if not os.path.isdir(skills_root):
        raise RuntimeError("GitHub repository does not contain a root-level skills directory")

    return sorted(
        name
        for name in os.listdir(skills_root)
        if os.path.isdir(os.path.join(skills_root, name)) and not name.startswith(".")
    )


def _resolve_repo_skill(repo_root: str, selected_skill: str | None) -> tuple[str, str]:
    skills_root = os.path.join(repo_root, "skills")
    available_skills = _list_repo_skills(repo_root)
    if not available_skills:
        raise RuntimeError("GitHub repository skills directory is empty")

    if selected_skill:
        if selected_skill not in available_skills:
            available = ", ".join(available_skills)
            raise RuntimeError(
                f"Skill '{selected_skill}' not found in repository skills directory. "
                f"Available skills: {available}"
            )
        return selected_skill, os.path.join(skills_root, selected_skill)

    if len(available_skills) > 1:
        available = ", ".join(available_skills)
        raise RuntimeError(
            "Repository contains multiple skills. Use --skill to choose one: "
            f"{available}"
        )

    skill_dir_name = available_skills[0]
    return skill_dir_name, os.path.join(skills_root, skill_dir_name)


def _install_skill_from_directory(
    skill_root: str,
    source_skill: str,
    source: dict,
    force: bool = False,
) -> dict:
    repo_meta = _load_skill_metadata(os.path.join(skill_root, "skill.json"))
    skill_name = str(repo_meta.get("name") or source_skill).strip()
    if not skill_name:
        skill_name = source_skill

    target_path = _skill_path(skill_name)
    if os.path.exists(target_path):
        if not force:
            raise FileExistsError(skill_name)
        shutil.rmtree(target_path)

    shutil.copytree(skill_root, target_path)
    merged_meta = dict(repo_meta)
    merged_meta["name"] = skill_name
    merged_meta["version"] = str(merged_meta.get("version") or "unknown")
    merged_meta["installed_at"] = _utc_now()
    merged_meta["status"] = "installed"
    merged_meta["source"] = {
        **source,
        "skill": source_skill,
    }
    _write_skill_metadata(skill_name, merged_meta)
    return merged_meta


def list_github_repo_skills(spec: str) -> list[str]:
    parsed = _parse_github_spec(spec)
    if parsed is None:
        raise RuntimeError("Unsupported GitHub URL")

    repo_root, _source = _extract_github_repo(parsed)
    cleanup_root = os.path.dirname(repo_root)
    try:
        return _list_repo_skills(repo_root)
    finally:
        shutil.rmtree(cleanup_root, ignore_errors=True)


def install_github_skills(
    spec: str,
    force: bool = False,
    selected_skills: list[str] | None = None,
) -> list[dict]:
    parsed = _parse_github_spec(spec)
    if parsed is None:
        raise RuntimeError("Unsupported GitHub URL")

    repo_root, source = _extract_github_repo(parsed)
    cleanup_root = os.path.dirname(repo_root)
    try:
        available_skills = _list_repo_skills(repo_root)
        if not available_skills:
            raise RuntimeError("GitHub repository skills directory is empty")

        if selected_skills:
            unknown = [name for name in selected_skills if name not in available_skills]
            if unknown:
                available = ", ".join(available_skills)
                missing = ", ".join(unknown)
                raise RuntimeError(
                    f"Skill '{missing}' not found in repository skills directory. "
                    f"Available skills: {available}"
                )
            targets = selected_skills
        else:
            targets = available_skills

        installed = []
        skills_root = os.path.join(repo_root, "skills")
        for source_skill in targets:
            skill_root = os.path.join(skills_root, source_skill)
            installed.append(
                _install_skill_from_directory(
                    skill_root,
                    source_skill,
                    source,
                    force=force,
                )
            )
        return installed
    finally:
        shutil.rmtree(cleanup_root, ignore_errors=True)


def _install_github_skill(
    spec: str,
    force: bool = False,
    selected_skill: str | None = None,
) -> dict:
    parsed = _parse_github_spec(spec)
    if parsed is None:
        raise RuntimeError("Unsupported GitHub URL")

    repo_root, source = _extract_github_repo(parsed)
    cleanup_root = os.path.dirname(repo_root)
    try:
        source_skill, skill_root = _resolve_repo_skill(repo_root, selected_skill)
        return _install_skill_from_directory(
            skill_root,
            source_skill,
            source,
            force=force,
        )
    finally:
        shutil.rmtree(cleanup_root, ignore_errors=True)


def install_skill(skill_name: str, force: bool = False, selected_skill: str | None = None) -> dict:
    """Install a local placeholder skill or fetch one from a GitHub repository URL."""
    if _looks_like_github_url(skill_name):
        return _install_github_skill(skill_name, force=force, selected_skill=selected_skill)
    if selected_skill:
        raise RuntimeError("--skill can only be used with a GitHub repository URL")
    return _install_placeholder_skill(skill_name, force=force)


def uninstall_skill(skill_name: str) -> None:
    path = _skill_path(skill_name)
    if not os.path.exists(path):
        raise FileNotFoundError(skill_name)
    shutil.rmtree(path)


def list_skills():
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(
        name for name in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, name)) and not name.startswith(".")
    )


def update_skill(skill_name=None, selected_skill: str | None = None):
    """Update one or all installed skills, including GitHub-backed skills."""
    targets = [skill_name] if skill_name else list_skills()
    updated = []
    for target in targets:
        try:
            if _looks_like_github_url(target):
                meta = install_skill(target, force=True, selected_skill=selected_skill)
                updated.append(meta["name"])
                continue

            if not os.path.isdir(_skill_path(target)):
                continue

            existing_meta = info_skill(target) or {}
            source = existing_meta.get("source") or {}
            install_spec = source.get("install_spec") or target
            source_skill = source.get("skill")
            meta = install_skill(
                install_spec,
                force=True,
                selected_skill=selected_skill or source_skill,
            )
            updated.append(meta["name"])
        except Exception:
            continue
    return updated


def info_skill(skill_name: str):
    mp = _meta_path(skill_name)
    if not os.path.isfile(mp):
        sp = _skill_path(skill_name)
        if not os.path.isdir(sp):
            return None
        return {"status": "installed", "version": "unknown"}
    with open(mp, "r", encoding="utf-8") as f:
        return json.load(f)
