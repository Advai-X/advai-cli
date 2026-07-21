from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


InstallDirectoryFn = Callable[[str, str, dict, bool], dict]


@dataclass
class SkillSearchResult:
    provider: str
    name: str
    install_spec: str
    remote_id: str | None = None
    version: str | None = None
    description: str = ""
    homepage: str | None = None
    exact: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResolvedSkill:
    provider: str
    name: str
    install_spec: str
    source_type: str
    remote_id: str | None = None
    version: str | None = None
    source_skill: str | None = None
    extracted_dir: str | None = None
    cleanup_dir: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


class SkillSourceProvider(Protocol):
    name: str

    def can_handle(self, spec: str) -> bool:
        ...

    def search(self, query: str, limit: int = 20) -> list[SkillSearchResult]:
        ...

    def resolve(
        self,
        spec: str,
        *,
        selected_skill: str | None = None,
        version: str | None = None,
    ) -> ResolvedSkill:
        ...

    def install(
        self,
        resolved: ResolvedSkill,
        *,
        force: bool,
        install_directory: InstallDirectoryFn,
    ) -> dict:
        ...

    def update(
        self,
        installed_metadata: dict,
        *,
        force: bool,
        install_directory: InstallDirectoryFn,
    ) -> dict:
        ...
