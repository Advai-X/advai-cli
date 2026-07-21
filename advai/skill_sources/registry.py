from advai.skill_sources.github import GitHubSkillProvider
from advai.skill_sources.skills_sh import SkillsShSkillProvider

_GITHUB_PROVIDER = GitHubSkillProvider()
_SKILLS_SH_PROVIDER = SkillsShSkillProvider()

_PROVIDERS = {
    "github": _GITHUB_PROVIDER,
    "skills_sh": _SKILLS_SH_PROVIDER,
    "skills.sh": _SKILLS_SH_PROVIDER,
}


def get_provider(name: str):
    key = str(name or "").strip().lower()
    return _PROVIDERS.get(key)


def list_providers():
    seen = set()
    providers = []
    for key in sorted(_PROVIDERS):
        provider = _PROVIDERS[key]
        provider_id = id(provider)
        if provider_id in seen:
            continue
        seen.add(provider_id)
        providers.append(provider)
    return providers


def detect_provider_from_spec(spec: str):
    for provider in list_providers():
        if provider.can_handle(spec):
            return provider
    return None


def search_providers(query: str, source: str | None = None, limit: int = 20):
    if source:
        provider = get_provider(source)
        if provider is None:
            raise RuntimeError(f"Unknown skill source '{source}'")
        return provider.search(query, limit=limit)

    results = []
    for provider in list_providers():
        results.extend(provider.search(query, limit=limit))
    return results[:limit]
