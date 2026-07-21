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

from advai.skill_sources.registry import detect_provider_from_spec, get_provider, search_providers
from advai.skill_platforms import get_skill_platform, resolve_platform_target

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


def _load_existing_metadata(skill_name: str) -> dict:
    return _load_skill_metadata(_meta_path(skill_name))


def _preserve_sync_targets(existing_meta: dict, metadata: dict) -> dict:
    merged = dict(metadata)
    sync_targets = existing_meta.get("sync_targets")
    if isinstance(sync_targets, list):
        merged["sync_targets"] = sync_targets
    return merged


def _sync_key(platform_key: str, project_dir: str | None) -> tuple[str, str | None]:
    normalized_project_dir = None
    if project_dir:
        normalized_project_dir = os.path.abspath(os.path.expanduser(project_dir))
    return platform_key, normalized_project_dir


def _skill_target_entry(
    platform_key: str,
    target_path: str,
    mode: str,
    project_dir: str | None,
) -> dict:
    return {
        "platform": platform_key,
        "path": os.path.abspath(target_path),
        "mode": mode,
        "project_dir": os.path.abspath(os.path.expanduser(project_dir))
        if project_dir
        else None,
        "synced_at": _utc_now(),
    }


def _replace_sync_target_entry(metadata: dict, target_entry: dict) -> dict:
    targets = []
    target_key = _sync_key(target_entry["platform"], target_entry.get("project_dir"))
    for item in metadata.get("sync_targets") or []:
        item_key = _sync_key(item.get("platform", ""), item.get("project_dir"))
        if item_key != target_key:
            targets.append(item)
    targets.append(target_entry)
    metadata["sync_targets"] = sorted(
        targets,
        key=lambda item: (item.get("platform", ""), item.get("project_dir") or ""),
    )
    return metadata


def _remove_path(path: str) -> None:
    if os.path.islink(path) or os.path.isfile(path):
        os.unlink(path)
        return
    if os.path.isdir(path):
        shutil.rmtree(path)


def _create_skill_target(source_path: str, target_path: str, mode: str) -> None:
    if mode not in {"symlink", "copy"}:
        raise ValueError("Sync mode must be 'symlink' or 'copy'")

    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    _remove_path(target_path)

    if mode == "symlink":
        os.symlink(source_path, target_path)
        return

    shutil.copytree(source_path, target_path)


def _sync_targets_for_skill(skill_name: str) -> list[dict]:
    metadata = info_skill(skill_name) or {}
    sync_targets = metadata.get("sync_targets") or []
    return [item for item in sync_targets if isinstance(item, dict)]


def _store_sync_target(skill_name: str, target_entry: dict) -> dict:
    metadata = info_skill(skill_name) or {}
    metadata = _replace_sync_target_entry(metadata, target_entry)
    _write_skill_metadata(skill_name, metadata)
    return metadata


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
    existing_meta = _load_existing_metadata(skill_name)
    if os.path.exists(target_path):
        if not force:
            raise FileExistsError(skill_name)
        shutil.rmtree(target_path)

    shutil.copytree(skill_root, target_path)
    merged_meta = dict(repo_meta)
    merged_meta["name"] = skill_name
    merged_meta["version"] = str(
        merged_meta.get("version") or source.get("resolved_version") or "unknown"
    )
    merged_meta["installed_at"] = _utc_now()
    merged_meta["status"] = "installed"
    merged_meta["source"] = {
        **source,
        "skill": source.get("skill") or source_skill,
    }
    merged_meta = _preserve_sync_targets(existing_meta, merged_meta)
    _write_skill_metadata(skill_name, merged_meta)
    return merged_meta


def list_github_repo_skills(spec: str) -> list[str]:
    provider = get_provider("github")
    if provider is None:
        raise RuntimeError("GitHub skill provider is not available")
    return provider.list_repo_skills(spec)


def install_github_skills(
    spec: str,
    force: bool = False,
    selected_skills: list[str] | None = None,
) -> list[dict]:
    provider = get_provider("github")
    if provider is None:
        raise RuntimeError("GitHub skill provider is not available")
    return provider.install_many(
        spec,
        force=force,
        selected_skills=selected_skills,
        install_directory=_install_skill_from_directory,
    )


def _install_github_skill(
    spec: str,
    force: bool = False,
    selected_skill: str | None = None,
) -> dict:
    provider = get_provider("github")
    if provider is None:
        raise RuntimeError("GitHub skill provider is not available")
    resolved = provider.resolve(spec, selected_skill=selected_skill)
    return provider.install(
        resolved,
        force=force,
        install_directory=_install_skill_from_directory,
    )


def rewrite_skill_source(skill_name: str, source: dict) -> dict:
    metadata = info_skill(skill_name)
    if metadata is None:
        raise FileNotFoundError(skill_name)
    metadata["source"] = source
    _write_skill_metadata(skill_name, metadata)
    return metadata


def search_skills(query: str, source: str | None = None, limit: int = 20) -> list:
    return search_providers(query, source=source, limit=limit)


def install_skill(
    skill_name: str,
    force: bool = False,
    selected_skill: str | None = None,
    source: str | None = None,
    version: str | None = None,
) -> dict:
    provider = get_provider(source) if source else detect_provider_from_spec(skill_name)
    if provider is None:
        raise RuntimeError(
            "Unable to determine skill source. Use --source or a provider-prefixed spec."
        )
    resolved = provider.resolve(
        skill_name,
        selected_skill=selected_skill,
        version=version,
    )
    installed = provider.install(
        resolved,
        force=force,
        install_directory=_install_skill_from_directory,
    )
    if installed.get("source"):
        installed = rewrite_skill_source(installed["name"], installed["source"])
    return installed


def uninstall_skill(skill_name: str) -> None:
    path = _skill_path(skill_name)
    if not os.path.exists(path):
        raise FileNotFoundError(skill_name)
    remove_all_skill_targets(skill_name)
    shutil.rmtree(path)


def list_skills():
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(
        name for name in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, name)) and not name.startswith(".")
    )


def _normalize_provider_name(source: dict) -> str | None:
    provider = str(source.get("provider") or "").strip().lower()
    if provider:
        return provider

    source_type = str(source.get("type") or "").strip().lower()
    install_spec = str(source.get("install_spec") or "").strip()
    url = str(source.get("url") or "").strip()
    if source_type == "github":
        return "github"
    if install_spec.startswith("https://github.com/") or url.startswith("https://github.com/"):
        return "github"
    return None


def update_skill(skill_name=None, selected_skill: str | None = None):
    """Update one or all installed skills."""
    targets = [skill_name] if skill_name else list_skills()
    updated = []
    for target in targets:
        try:
            if not os.path.isdir(_skill_path(target)):
                continue

            existing_meta = info_skill(target) or {}
            source = existing_meta.get("source") or {}
            provider_name = _normalize_provider_name(source)
            if not provider_name:
                continue

            provider = get_provider(provider_name)
            if provider is None:
                continue
            if selected_skill and provider_name != "github":
                raise RuntimeError("--skill is only supported for GitHub repository installs")

            meta = provider.update(
                existing_meta,
                force=True,
                install_directory=_install_skill_from_directory,
            )
            if meta.get("source"):
                meta = rewrite_skill_source(meta["name"], meta["source"])
            resync_skill_targets(meta["name"])
            updated.append(meta["name"])
        except Exception:
            continue
    return updated


def sync_skill_to_platform(
    skill_name: str,
    platform_key: str,
    project_dir: str | None = None,
    mode: str = "symlink",
    force: bool = False,
) -> dict:
    source_path = _skill_path(skill_name)
    if not os.path.isdir(source_path):
        raise FileNotFoundError(skill_name)

    target = resolve_platform_target(platform_key, project_dir=project_dir)
    target_path = os.path.join(target["skills_dir"], skill_name)
    if os.path.exists(target_path) and not force:
        same_symlink = (
            mode == "symlink"
            and os.path.islink(target_path)
            and os.path.realpath(target_path) == os.path.realpath(source_path)
        )
        if not same_symlink:
            raise FileExistsError(target_path)

    _create_skill_target(source_path, target_path, mode)
    metadata = _store_sync_target(
        skill_name,
        _skill_target_entry(
            platform_key=target["platform"]["key"],
            target_path=target_path,
            mode=mode,
            project_dir=target["project_dir"],
        ),
    )
    return {
        "skill": skill_name,
        "platform": target["platform"],
        "path": target_path,
        "mode": mode,
        "metadata": metadata,
    }


def unsync_skill_from_platform(skill_name: str, platform_key: str, project_dir: str | None = None) -> dict:
    metadata = info_skill(skill_name)
    if metadata is None:
        raise FileNotFoundError(skill_name)

    normalized_key = get_skill_platform(platform_key)
    if normalized_key is None:
        raise KeyError(f"Unknown platform '{platform_key}'")

    match_key = _sync_key(normalized_key["key"], project_dir)
    kept_targets = []
    removed_targets = []
    for item in metadata.get("sync_targets") or []:
        item_key = _sync_key(item.get("platform", ""), item.get("project_dir"))
        if item_key == match_key:
            removed_targets.append(item)
        else:
            kept_targets.append(item)

    if not removed_targets:
        raise FileNotFoundError(
            f"Skill '{skill_name}' is not synced to platform '{normalized_key['key']}'"
        )

    for item in removed_targets:
        path = item.get("path")
        if path and os.path.exists(path):
            _remove_path(path)

    metadata["sync_targets"] = kept_targets
    _write_skill_metadata(skill_name, metadata)
    return {
        "skill": skill_name,
        "platform": normalized_key,
        "removed": removed_targets,
    }


def remove_all_skill_targets(skill_name: str) -> list[dict]:
    metadata = info_skill(skill_name)
    if metadata is None:
        return []

    removed = []
    for item in metadata.get("sync_targets") or []:
        path = item.get("path")
        if path and os.path.exists(path):
            _remove_path(path)
        removed.append(item)

    if removed:
        metadata["sync_targets"] = []
        _write_skill_metadata(skill_name, metadata)
    return removed


def resync_skill_targets(skill_name: str) -> list[dict]:
    if not os.path.isdir(_skill_path(skill_name)):
        return []

    synced = []
    for item in _sync_targets_for_skill(skill_name):
        synced.append(
            sync_skill_to_platform(
                skill_name,
                item["platform"],
                project_dir=item.get("project_dir"),
                mode=item.get("mode") or "symlink",
                force=True,
            )
        )
    return synced


def list_skill_sync_targets(skill_name: str) -> list[dict]:
    metadata = info_skill(skill_name)
    if metadata is None:
        raise FileNotFoundError(skill_name)
    return _sync_targets_for_skill(skill_name)


def info_skill(skill_name: str):
    mp = _meta_path(skill_name)
    if not os.path.isfile(mp):
        sp = _skill_path(skill_name)
        if not os.path.isdir(sp):
            return None
        return {"status": "installed", "version": "unknown", "sync_targets": []}
    with open(mp, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("sync_targets", [])
    return data
