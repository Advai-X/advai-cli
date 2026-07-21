import io
import json
import os
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile

from advai.skill_sources.base import ResolvedSkill, SkillSearchResult

GITHUB_REPO_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"
)
GITHUB_TREE_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/tree/(?P<ref>.+?)/?$"
)


class GitHubSkillProvider:
    name = "github"

    def can_handle(self, spec: str) -> bool:
        candidate = str(spec or "").strip()
        return bool(
            GITHUB_REPO_PATTERN.match(candidate) or GITHUB_TREE_PATTERN.match(candidate)
        )

    def search(self, query: str, limit: int = 20) -> list[SkillSearchResult]:
        _ = (query, limit)
        return []

    def resolve(
        self,
        spec: str,
        *,
        selected_skill: str | None = None,
        version: str | None = None,
    ) -> ResolvedSkill:
        _ = version
        parsed = _parse_github_spec(spec)
        if parsed is None:
            raise RuntimeError("Unsupported GitHub URL")

        repo_root, source = _extract_github_repo(parsed)
        cleanup_root = os.path.dirname(repo_root)
        source_skill, skill_root = _resolve_repo_skill(repo_root, selected_skill)
        return ResolvedSkill(
            provider=self.name,
            name=source_skill,
            install_spec=parsed["install_spec"],
            source_type="repository",
            remote_id=f"{parsed['owner']}/{parsed['repo']}",
            version=source["ref"],
            source_skill=source_skill,
            extracted_dir=skill_root,
            cleanup_dir=cleanup_root,
            metadata=source,
        )

    def install(
        self,
        resolved: ResolvedSkill,
        *,
        force: bool,
        install_directory,
    ) -> dict:
        try:
            return install_directory(
                resolved.extracted_dir or "",
                resolved.source_skill or resolved.name,
                {
                    **resolved.metadata,
                    "provider": self.name,
                    "type": "github",
                    "remote_id": resolved.remote_id,
                    "resolved_version": resolved.version,
                },
                force,
            )
        finally:
            if resolved.cleanup_dir:
                shutil.rmtree(resolved.cleanup_dir, ignore_errors=True)

    def update(
        self,
        installed_metadata: dict,
        *,
        force: bool,
        install_directory,
    ) -> dict:
        source = installed_metadata.get("source") or {}
        install_spec = source.get("install_spec")
        selected_skill = source.get("skill")
        if not install_spec:
            raise RuntimeError("Installed GitHub skill is missing install_spec")
        resolved = self.resolve(install_spec, selected_skill=selected_skill)
        return self.install(
            resolved,
            force=force,
            install_directory=install_directory,
        )

    def list_repo_skills(self, spec: str) -> list[str]:
        parsed = _parse_github_spec(spec)
        if parsed is None:
            raise RuntimeError("Unsupported GitHub URL")

        repo_root, _source = _extract_github_repo(parsed)
        cleanup_root = os.path.dirname(repo_root)
        try:
            return _list_repo_skills(repo_root)
        finally:
            shutil.rmtree(cleanup_root, ignore_errors=True)

    def install_many(
        self,
        spec: str,
        *,
        force: bool = False,
        selected_skills: list[str] | None = None,
        install_directory,
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
                    install_directory(
                        skill_root,
                        source_skill,
                        {
                            **source,
                            "provider": self.name,
                            "type": "github",
                            "remote_id": f"{parsed['owner']}/{parsed['repo']}",
                            "resolved_version": source["ref"],
                        },
                        force,
                    )
                )
            return installed
        finally:
            shutil.rmtree(cleanup_root, ignore_errors=True)


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
    archive_url = f"https://api.github.com/repos/{parsed['owner']}/{parsed['repo']}/zipball/{ref}"
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
