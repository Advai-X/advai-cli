import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from advai.skill_sources.base import ResolvedSkill, SkillSearchResult

SKILLS_SH_PAGE_PATTERN = re.compile(
    r"^https?://(?:www\.)?skills\.sh/(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<skill>[^/?#]+?)/?$"
)
SKILLS_SH_SPEC_PATTERN = re.compile(
    r"^(?:skills\.sh|skills_sh):(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<skill>[^/?#]+?)$"
)
SKILL_LINK_PATTERN = re.compile(
    r"https?://(?:www\.)?skills\.sh/"
    r"(?P<owner>[^/]+)/(?P<repo>[^/]+)/(?P<skill>[^/?#]+?)(?=[\"')\s<])"
)
GITHUB_REPO_LINK_PATTERN = re.compile(
    r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/\"'#?]+)"
)
SUMMARY_PATTERN = re.compile(
    r"Summary\s+(?P<summary>.+?)(?:\n\s*\n|\n#|\nSKILL\.md|\nRelated skills)",
    re.DOTALL,
)
RESERVED_SEGMENTS = {"docs", "topic", "official", "trending", "hot", "search"}


class SkillsShSkillProvider:
    name = "skills_sh"
    display_name = "skills.sh"

    def can_handle(self, spec: str) -> bool:
        value = str(spec or "").strip()
        return bool(
            SKILLS_SH_PAGE_PATTERN.match(value) or SKILLS_SH_SPEC_PATTERN.match(value)
        )

    def search(self, query: str, limit: int = 20) -> list[SkillSearchResult]:
        term = str(query or "").strip()
        if len(term) < 2:
            return []

        api_token = _skills_sh_api_token()
        if api_token:
            try:
                return _search_via_api(term, limit=limit, token=api_token)
            except RuntimeError:
                pass

        return _search_via_html(term, limit=limit)

    def resolve(
        self,
        spec: str,
        *,
        selected_skill: str | None = None,
        version: str | None = None,
    ) -> ResolvedSkill:
        if selected_skill:
            raise RuntimeError("--skill is not supported for skills.sh installs")
        if version:
            raise RuntimeError("--version is not supported for skills.sh installs yet")

        parsed = self._normalize_spec(spec)
        api_token = _skills_sh_api_token()
        if api_token:
            try:
                data = _resolve_via_api(parsed, token=api_token)
            except RuntimeError:
                data = _resolve_via_html(parsed)
        else:
            data = _resolve_via_html(parsed)

        return ResolvedSkill(
            provider=self.name,
            name=parsed["skill"],
            install_spec=parsed["install_spec"],
            source_type="directory",
            remote_id=f"{parsed['owner']}/{parsed['repo']}/{parsed['skill']}",
            source_skill=parsed["skill"],
            metadata={
                "page_url": parsed["page_url"],
                "repo_path": f"{parsed['owner']}/{parsed['repo']}",
                "github_url": data["github_url"],
                "summary": data.get("summary") or "",
            },
        )

    def install(self, resolved: ResolvedSkill, *, force: bool, install_directory) -> dict:
        from advai.skill_sources.registry import get_provider

        github_provider = get_provider("github")
        if github_provider is None:
            raise RuntimeError("GitHub skill provider is not available")

        github_resolved = github_provider.resolve(
            resolved.metadata["github_url"],
            selected_skill=resolved.source_skill,
        )
        installed = github_provider.install(
            github_resolved,
            force=force,
            install_directory=install_directory,
        )
        upstream = installed.get("source") or {}
        installed["source"] = {
            "provider": self.name,
            "type": "directory",
            "install_spec": resolved.install_spec,
            "remote_id": resolved.remote_id,
            "page_url": resolved.metadata["page_url"],
            "repo_path": resolved.metadata["repo_path"],
            "skill": resolved.source_skill,
            "summary": resolved.metadata.get("summary") or "",
            "upstream": upstream,
        }
        return installed

    def update(self, installed_metadata: dict, *, force: bool, install_directory) -> dict:
        source = installed_metadata.get("source") or {}
        install_spec = source.get("install_spec")
        if not install_spec:
            raise RuntimeError("Installed skills.sh skill is missing install_spec")
        resolved = self.resolve(install_spec)
        return self.install(
            resolved,
            force=force,
            install_directory=install_directory,
        )

    def _normalize_spec(self, spec: str) -> dict:
        value = str(spec or "").strip()

        match = SKILLS_SH_PAGE_PATTERN.match(value)
        if match:
            data = match.groupdict()
            return {
                "owner": data["owner"],
                "repo": data["repo"],
                "skill": data["skill"],
                "page_url": f"https://skills.sh/{data['owner']}/{data['repo']}/{data['skill']}",
                "install_spec": f"skills.sh:{data['owner']}/{data['repo']}/{data['skill']}",
            }

        match = SKILLS_SH_SPEC_PATTERN.match(value)
        if match:
            data = match.groupdict()
            return {
                "owner": data["owner"],
                "repo": data["repo"],
                "skill": data["skill"],
                "page_url": f"https://skills.sh/{data['owner']}/{data['repo']}/{data['skill']}",
                "install_spec": f"skills.sh:{data['owner']}/{data['repo']}/{data['skill']}",
            }

        if not value:
            raise RuntimeError("Unsupported skills.sh skill spec")

        return self._normalize_search_spec(value)

    def _normalize_search_spec(self, query: str) -> dict:
        term = str(query or "").strip()
        results = self.search(term, limit=10)
        if not results:
            raise RuntimeError(f"No skills found on skills.sh for '{term}'")

        normalized_term = _normalize_skill_term(term)
        exact_matches = []
        for item in results:
            normalized_name = _normalize_skill_term(item.name)
            normalized_slug = _normalize_skill_term(
                str((item.remote_id or "").rsplit("/", 1)[-1])
            )
            if normalized_name == normalized_term or normalized_slug == normalized_term:
                exact_matches.append(item)

        if len(exact_matches) == 1:
            chosen = exact_matches[0]
        elif len(exact_matches) > 1 or len(results) > 1:
            choices = ", ".join(item.install_spec for item in (exact_matches or results[:5]))
            raise RuntimeError(
                f"Multiple skills found on skills.sh for '{term}'. "
                f"Use a full skills.sh spec or URL: {choices}"
            )
        else:
            chosen = results[0]

        return self._normalize_spec(chosen.install_spec)


def _skills_sh_api_token() -> str:
    for key in ("ADVAI_SKILLS_SH_TOKEN", "SKILLS_SH_TOKEN", "VERCEL_OIDC_TOKEN"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalize_skill_term(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.replace("_", "-").replace(" ", "-")
    return re.sub(r"-+", "-", normalized)


def _fetch_bytes(url: str, headers: dict | None = None) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "advai-cli",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(body or exc.reason) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def _fetch_text(url: str) -> str:
    try:
        return _fetch_bytes(
            url,
            headers={"Accept": "text/html,application/xhtml+xml"},
        ).decode("utf-8", errors="replace")
    except RuntimeError as exc:
        message = str(exc or "").strip() or "unknown error"
        if "http" in message.lower() or "error" in message.lower():
            raise RuntimeError(f"Failed to fetch skills.sh page: {message}") from exc
        raise RuntimeError(f"Unable to reach skills.sh: {message}") from exc


def _fetch_json(url: str, token: str) -> dict:
    try:
        payload = _fetch_bytes(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
    except RuntimeError as exc:
        raise RuntimeError(f"skills.sh API request failed: {exc}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("skills.sh API returned invalid JSON") from exc


def _search_via_api(query: str, limit: int, token: str) -> list[SkillSearchResult]:
    url = f"https://skills.sh/api/v1/skills/search?q={urllib.parse.quote(query)}&limit={limit}"
    payload = _fetch_json(url, token)
    results = []
    for item in payload.get("data") or []:
        remote_id = str(
            item.get("id")
            or "/".join(
                part
                for part in (
                    item.get("source"),
                    item.get("slug"),
                )
                if part
            )
        ).strip()
        if not remote_id:
            continue
        slug = str(item.get("slug") or remote_id.rsplit("/", 1)[-1]).strip()
        results.append(
            SkillSearchResult(
                provider="skills_sh",
                name=str(item.get("name") or slug).strip() or slug,
                install_spec=f"skills.sh:{remote_id}",
                remote_id=remote_id,
                description=str(item.get("description") or "").strip(),
                homepage=str(item.get("url") or f"https://skills.sh/{remote_id}").strip(),
                exact=slug.lower() == query.lower()
                or str(item.get("name") or "").strip().lower() == query.lower(),
                raw=item,
            )
        )
    return results


def _search_via_html(query: str, limit: int) -> list[SkillSearchResult]:
    url = f"https://skills.sh/search?q={urllib.parse.quote(query)}"
    page = _fetch_text(url)
    seen = set()
    results = []
    for owner, repo, skill in _extract_skill_links(page):
        remote_id = f"{owner}/{repo}/{skill}"
        if remote_id in seen:
            continue
        seen.add(remote_id)
        results.append(
            SkillSearchResult(
                provider="skills_sh",
                name=skill,
                install_spec=f"skills.sh:{remote_id}",
                remote_id=remote_id,
                homepage=f"https://skills.sh/{remote_id}",
                exact=skill.lower() == query.lower(),
            )
        )
        if len(results) >= limit:
            break
    return results


def _resolve_via_api(parsed: dict, token: str) -> dict:
    remote_id = f"{parsed['owner']}/{parsed['repo']}/{parsed['skill']}"
    url = f"https://skills.sh/api/v1/skills/{remote_id}"
    payload = _fetch_json(url, token)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload

    github_url = str(
        data.get("installUrl")
        or data.get("repository")
        or data.get("repoUrl")
        or ""
    ).strip()
    if not github_url and str(data.get("sourceType") or "").strip().lower() == "github":
        source = str(data.get("source") or "").strip()
        if source:
            github_url = f"https://github.com/{source}"
    if not github_url:
        raise RuntimeError("skills.sh API detail is missing GitHub repository data")

    summary = str(
        data.get("summary")
        or data.get("description")
        or data.get("excerpt")
        or ""
    ).strip()
    return {
        "github_url": github_url,
        "summary": summary,
    }


def _resolve_via_html(parsed: dict) -> dict:
    page = _fetch_text(parsed["page_url"])
    github_url = _extract_github_repo_url(page)
    if not github_url:
        raise RuntimeError("skills.sh skill page does not expose a GitHub repository")
    return {
        "github_url": github_url,
        "summary": _extract_summary(page),
    }


def _extract_skill_links(page: str) -> list[tuple[str, str, str]]:
    results = []
    for match in SKILL_LINK_PATTERN.finditer(page):
        owner = match.group("owner")
        repo = match.group("repo")
        skill = match.group("skill")
        if owner in RESERVED_SEGMENTS or repo in RESERVED_SEGMENTS:
            continue
        results.append((owner, repo, skill))
    return results


def _extract_github_repo_url(page: str) -> str | None:
    match = GITHUB_REPO_LINK_PATTERN.search(page)
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    return f"https://github.com/{owner}/{repo}"


def _extract_summary(page: str) -> str:
    match = SUMMARY_PATTERN.search(page)
    if not match:
        return ""
    summary = html.unescape(match.group("summary"))
    return re.sub(r"\s+", " ", summary).strip("* ").strip()
