import io
import json
import os
import tempfile
import unittest
import zipfile
from unittest import mock

from click.testing import CliRunner

from advai.cli import cli
from advai.ai_client import (
    AIClientError,
    AIConfig,
    list_selectable_agents,
    list_selectable_models,
    load_ai_config,
    request_chat_completion,
)
from advai.kb import (
    add_document,
    create_knowledge_base,
    search_knowledge_base,
    sync_knowledge_base,
)
from advai.cli_manager import install_github_clis, list_github_repo_clis
from advai.skills import info_skill, install_skill, update_skill
from advai.skill_sources.skills_sh import SkillsShSkillProvider


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class _FakeBytesResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class _FakeHeaders:
    def get_content_charset(self):
        return "utf-8"


class _FakeTextResponse:
    def __init__(self, payload: str):
        self._payload = payload
        self.headers = _FakeHeaders()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload.encode("utf-8")


class AIClientTests(unittest.TestCase):
    def test_load_ai_config_uses_defaults(self):
        with mock.patch.dict("os.environ", {"ADVAI_API_KEY": "secret"}, clear=True):
            config = load_ai_config()

        self.assertEqual(config.api_key, "secret")
        self.assertEqual(config.agent, "default")
        self.assertEqual(config.model, "gpt-4o-mini")
        self.assertEqual(config.base_url, "https://api.openai.com/v1")
        self.assertEqual(config.timeout, 120)

    def test_load_ai_config_requires_api_key(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(AIClientError):
                load_ai_config()

    def test_request_chat_completion_parses_message(self):
        config = AIConfig(
            api_key="secret",
            agent="default",
            model="demo-model",
            base_url="https://example.com/v1",
            system_prompt="Be helpful",
            timeout=30,
        )

        with mock.patch(
            "urllib.request.urlopen",
            return_value=_FakeResponse(
                {"choices": [{"message": {"content": "Hello from the model"}}]}
            ),
        ):
            reply = request_chat_completion(config, [{"role": "user", "content": "Hi"}])

        self.assertEqual(reply, "Hello from the model")

    def test_list_selectable_models_includes_current_model_first(self):
        with mock.patch.dict("os.environ", {"ADVAI_MODELS": "gpt-4.1,gpt-4o-mini"}, clear=True):
            models = list_selectable_models("custom-model")

        self.assertEqual(models, ["custom-model", "gpt-4.1", "gpt-4o-mini"])

    def test_list_selectable_agents_includes_current_agent_first(self):
        with mock.patch.dict("os.environ", {"ADVAI_AGENTS": "default,coder"}, clear=True):
            agents = list_selectable_agents("reviewer")

        self.assertEqual(agents, ["reviewer", "default", "coder"])


class KnowledgeBaseTests(unittest.TestCase):
    def test_create_add_search_and_sync_knowledge_base(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "README.md")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("homebrew install advai\n")

            with mock.patch("advai.kb.KBS_DIR", os.path.join(temp_dir, "kbs")):
                create_knowledge_base("team-wiki")
                document = add_document("team-wiki", source_path)
                results = search_knowledge_base("team-wiki", "homebrew")

                with open(source_path, "w", encoding="utf-8") as handle:
                    handle.write("homebrew core formula\n")
                sync_result = sync_knowledge_base("team-wiki")
                synced_results = search_knowledge_base("team-wiki", "formula")

        self.assertEqual(document["display_name"], "README.md")
        self.assertEqual(results[0]["line_number"], 1)
        self.assertIn("homebrew install advai", results[0]["line"])
        self.assertEqual(sync_result["synced"], 1)
        self.assertEqual(sync_result["missing"], [])
        self.assertEqual(synced_results[0]["document"], "README.md")
        self.assertIn("homebrew core formula", synced_results[0]["line"])

    def test_cli_commands_manage_knowledge_base(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = os.path.join(temp_dir, "README.md")
            with open(source_path, "w", encoding="utf-8") as handle:
                handle.write("homebrew install advai\n")

            patched_kbs_dir = os.path.join(temp_dir, "kbs")
            with mock.patch("advai.kb.KBS_DIR", patched_kbs_dir), mock.patch(
                "advai.cli.KBS_DIR", patched_kbs_dir
            ):
                create_result = runner.invoke(cli, ["kb", "create", "team-wiki"])
                add_result = runner.invoke(
                    cli,
                    ["kb", "doc", "add", "team-wiki", source_path],
                )
                search_result = runner.invoke(
                    cli,
                    ["kb", "search", "team-wiki", "homebrew"],
                )
                sync_result = runner.invoke(cli, ["kb", "sync", "team-wiki"])

        self.assertEqual(create_result.exit_code, 0)
        self.assertIn("Knowledge base 'team-wiki' created", create_result.output)
        self.assertEqual(add_result.exit_code, 0)
        self.assertIn("Added document 'README.md'", add_result.output)
        self.assertEqual(search_result.exit_code, 0)
        self.assertIn("Search results for 'homebrew' in 'team-wiki':", search_result.output)
        self.assertIn("README.md:1: homebrew install advai", search_result.output)
        self.assertEqual(sync_result.exit_code, 0)
        self.assertIn("Knowledge base 'team-wiki' synced: 1/1 documents updated", sync_result.output)


class SkillGithubInstallTests(unittest.TestCase):
    def _build_repo_zip(self, files: dict[str, str]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for path, content in files.items():
                archive.writestr(f"acme-demo-skill-main/{path}", content)
        return buffer.getvalue()

    def test_install_skill_from_github_url(self):
        repo_zip = self._build_repo_zip(
            {
                "skills/demo-skill/skill.json": json.dumps(
                    {"name": "demo-skill", "version": "1.2.3"}
                ),
                "skills/demo-skill/README.md": "demo skill",
            }
        )

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://api.github.com/repos/acme/demo-skill":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/demo-skill/zipball/main":
                return _FakeBytesResponse(repo_zip)
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("advai.skills.SKILLS_DIR", temp_dir):
                with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    metadata = install_skill("https://github.com/acme/demo-skill")

        self.assertEqual(metadata["name"], "demo-skill")
        self.assertEqual(metadata["version"], "1.2.3")
        self.assertEqual(metadata["source"]["provider"], "github")
        self.assertEqual(metadata["source"]["type"], "github")
        self.assertEqual(metadata["source"]["ref"], "main")
        self.assertEqual(metadata["source"]["skill"], "demo-skill")
        self.assertTrue(metadata["installed_at"].endswith("Z"))

    def test_install_skill_requires_selection_when_repo_contains_multiple_skills(self):
        repo_zip = self._build_repo_zip(
            {
                "skills/alpha/skill.json": json.dumps({"name": "alpha", "version": "1.0.0"}),
                "skills/beta/skill.json": json.dumps({"name": "beta", "version": "1.0.0"}),
            }
        )

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://api.github.com/repos/acme/demo-skill":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/demo-skill/zipball/main":
                return _FakeBytesResponse(repo_zip)
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("advai.skills.SKILLS_DIR", temp_dir):
                with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    with self.assertRaisesRegex(RuntimeError, "Use --skill"):
                        install_skill("https://github.com/acme/demo-skill")

                    metadata = install_skill(
                        "https://github.com/acme/demo-skill",
                        selected_skill="beta",
                    )

        self.assertEqual(metadata["name"], "beta")
        self.assertEqual(metadata["source"]["skill"], "beta")

    def test_update_skill_reuses_saved_github_source(self):
        first_zip = self._build_repo_zip(
            {
                "skills/demo-skill/skill.json": json.dumps(
                    {"name": "demo-skill", "version": "1.0.0"}
                ),
                "skills/demo-skill/README.md": "v1",
            }
        )
        second_zip = self._build_repo_zip(
            {
                "skills/demo-skill/skill.json": json.dumps(
                    {"name": "demo-skill", "version": "2.0.0"}
                ),
                "skills/demo-skill/README.md": "v2",
            }
        )
        state = {"zip_payload": first_zip}

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://api.github.com/repos/acme/demo-skill":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/demo-skill/zipball/main":
                return _FakeBytesResponse(state["zip_payload"])
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("advai.skills.SKILLS_DIR", temp_dir):
                with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    install_skill("https://github.com/acme/demo-skill")
                    state["zip_payload"] = second_zip
                    updated = update_skill("demo-skill")
                    metadata = info_skill("demo-skill")

        self.assertEqual(updated, ["demo-skill"])
        self.assertEqual(metadata["version"], "2.0.0")
        self.assertEqual(metadata["source"]["install_spec"], "https://github.com/acme/demo-skill")
        self.assertEqual(metadata["source"]["skill"], "demo-skill")

    def test_install_skill_rejects_non_github_input(self):
        with self.assertRaisesRegex(
            RuntimeError,
            "Unable to determine skill source",
        ):
            install_skill("demo-skill")


class SkillsShProviderTests(unittest.TestCase):
    def test_skills_sh_can_handle_url_and_prefixed_spec(self):
        provider = SkillsShSkillProvider()
        self.assertTrue(
            provider.can_handle("https://skills.sh/vercel-labs/skills/find-skills")
        )
        self.assertTrue(provider.can_handle("skills.sh:vercel-labs/skills/find-skills"))
        self.assertTrue(provider.can_handle("skills_sh:vercel-labs/skills/find-skills"))
        self.assertFalse(provider.can_handle("find-skills"))

    def test_skills_sh_search_extracts_results_from_html(self):
        provider = SkillsShSkillProvider()
        html_payload = """
        <a href="https://www.skills.sh/vercel-labs/skills/find-skills">find-skills</a>
        <a href="https://www.skills.sh/anthropics/skills/frontend-design">frontend-design</a>
        """
        with mock.patch(
            "advai.skill_sources.skills_sh._fetch_text",
            return_value=html_payload,
        ):
            results = provider.search("design", limit=10)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].provider, "skills_sh")
        self.assertEqual(
            results[0].install_spec,
            "skills.sh:vercel-labs/skills/find-skills",
        )

    def test_skills_sh_search_prefers_api_when_token_is_set(self):
        provider = SkillsShSkillProvider()
        api_payload = {
            "data": [
                {
                    "id": "vercel-labs/skills/find-skills",
                    "slug": "find-skills",
                    "name": "Find Skills",
                    "description": "Discover skills",
                    "url": "https://skills.sh/vercel-labs/skills/find-skills",
                }
            ]
        }
        with mock.patch(
            "advai.skill_sources.skills_sh._skills_sh_api_token",
            return_value="token",
        ), mock.patch(
            "advai.skill_sources.skills_sh._fetch_json",
            return_value=api_payload,
        ) as api_mock, mock.patch(
            "advai.skill_sources.skills_sh._fetch_text"
        ) as html_mock:
            results = provider.search("find", limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Find Skills")
        api_mock.assert_called_once()
        html_mock.assert_not_called()

    def test_skills_sh_search_falls_back_to_html_when_api_fails(self):
        provider = SkillsShSkillProvider()
        html_payload = """
        <a href="https://www.skills.sh/vercel-labs/skills/find-skills">find-skills</a>
        """
        with mock.patch(
            "advai.skill_sources.skills_sh._skills_sh_api_token",
            return_value="token",
        ), mock.patch(
            "advai.skill_sources.skills_sh._fetch_json",
            side_effect=RuntimeError("authentication_required"),
        ), mock.patch(
            "advai.skill_sources.skills_sh._fetch_text",
            return_value=html_payload,
        ):
            results = provider.search("find", limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].install_spec, "skills.sh:vercel-labs/skills/find-skills")

    def test_skills_sh_resolve_prefers_api_when_token_is_set(self):
        provider = SkillsShSkillProvider()
        api_payload = {
            "sourceType": "github",
            "source": "vercel-labs/skills",
            "summary": "Discover and install skills.",
        }
        with mock.patch(
            "advai.skill_sources.skills_sh._skills_sh_api_token",
            return_value="token",
        ), mock.patch(
            "advai.skill_sources.skills_sh._fetch_json",
            return_value=api_payload,
        ) as api_mock, mock.patch(
            "advai.skill_sources.skills_sh._fetch_text"
        ) as html_mock:
            resolved = provider.resolve("skills.sh:vercel-labs/skills/find-skills")

        self.assertEqual(resolved.metadata["github_url"], "https://github.com/vercel-labs/skills")
        self.assertEqual(resolved.metadata["summary"], "Discover and install skills.")
        api_mock.assert_called_once()
        html_mock.assert_not_called()

    def test_skills_sh_resolve_supports_bare_name_with_unique_match(self):
        provider = SkillsShSkillProvider()
        with mock.patch.object(
            provider,
            "search",
            return_value=[
                type(
                    "Result",
                    (),
                    {
                        "name": "find-skills",
                        "install_spec": "skills.sh:vercel-labs/skills/find-skills",
                        "remote_id": "vercel-labs/skills/find-skills",
                    },
                )()
            ],
        ), mock.patch(
            "advai.skill_sources.skills_sh._skills_sh_api_token",
            return_value="",
        ), mock.patch(
            "advai.skill_sources.skills_sh._fetch_text",
            return_value="Repository https://github.com/vercel-labs/skills",
        ):
            resolved = provider.resolve("find-skills")

        self.assertEqual(resolved.install_spec, "skills.sh:vercel-labs/skills/find-skills")
        self.assertEqual(resolved.metadata["github_url"], "https://github.com/vercel-labs/skills")

    def test_skills_sh_resolve_rejects_ambiguous_bare_name(self):
        provider = SkillsShSkillProvider()
        with mock.patch.object(
            provider,
            "search",
            return_value=[
                type(
                    "Result",
                    (),
                    {
                        "name": "find-skills",
                        "install_spec": "skills.sh:vercel-labs/skills/find-skills",
                        "remote_id": "vercel-labs/skills/find-skills",
                    },
                )(),
                type(
                    "Result",
                    (),
                    {
                        "name": "find-skills",
                        "install_spec": "skills.sh:acme/skills/find-skills",
                        "remote_id": "acme/skills/find-skills",
                    },
                )(),
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "Multiple skills found on skills.sh"):
                provider.resolve("find-skills")

    def test_install_skill_from_skills_sh_url_delegates_to_github(self):
        repo_zip = SkillGithubInstallTests()._build_repo_zip(
            {
                "skills/find-skills/skill.json": json.dumps(
                    {"name": "find-skills", "version": "1.2.3"}
                ),
                "skills/find-skills/README.md": "demo skill",
            }
        )
        detail_html = """
        # find-skills
        Summary
        Discover and install skills.

        Repository
        https://github.com/vercel-labs/skills
        """

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://skills.sh/vercel-labs/skills/find-skills":
                return _FakeTextResponse(detail_html)
            if url == "https://api.github.com/repos/vercel-labs/skills":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/vercel-labs/skills/zipball/main":
                return _FakeBytesResponse(repo_zip)
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("advai.skills.SKILLS_DIR", temp_dir):
                with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    metadata = install_skill(
                        "https://skills.sh/vercel-labs/skills/find-skills"
                    )

        self.assertEqual(metadata["name"], "find-skills")
        self.assertEqual(metadata["source"]["provider"], "skills_sh")
        self.assertEqual(
            metadata["source"]["upstream"]["provider"],
            "github",
        )
        self.assertEqual(metadata["source"]["skill"], "find-skills")

    def test_install_skill_from_skills_sh_name_with_source(self):
        repo_zip = SkillGithubInstallTests()._build_repo_zip(
            {
                "skills/find-skills/skill.json": json.dumps(
                    {"name": "find-skills", "version": "1.2.3"}
                ),
                "skills/find-skills/README.md": "demo skill",
            }
        )
        detail_html = """
        # find-skills
        Repository
        https://github.com/vercel-labs/skills
        """

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://skills.sh/vercel-labs/skills/find-skills":
                return _FakeTextResponse(detail_html)
            if url == "https://api.github.com/repos/vercel-labs/skills":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/vercel-labs/skills/zipball/main":
                return _FakeBytesResponse(repo_zip)
            raise AssertionError(f"Unexpected URL: {url}")

        fake_result = type(
            "Result",
            (),
            {
                "name": "find-skills",
                "install_spec": "skills.sh:vercel-labs/skills/find-skills",
                "remote_id": "vercel-labs/skills/find-skills",
            },
        )()

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("advai.skills.SKILLS_DIR", temp_dir):
                with mock.patch.object(
                    SkillsShSkillProvider,
                    "search",
                    return_value=[fake_result],
                ), mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ):
                    metadata = install_skill("find-skills", source="skills_sh")

        self.assertEqual(metadata["name"], "find-skills")
        self.assertEqual(metadata["source"]["provider"], "skills_sh")


class ExternalCliGithubInstallTests(unittest.TestCase):
    def _build_repo_zip(self, files: dict[str, str]) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            for path, content in files.items():
                archive.writestr(f"acme-demo-cli-main/{path}", content)
        return buffer.getvalue()

    def test_install_github_clis_registers_manifest_from_clis_directory(self):
        repo_zip = self._build_repo_zip(
            {
                "clis/demo-cli/cli.json": json.dumps(
                    {
                        "name": "demo-cli",
                        "binary": "demo",
                        "install": "brew install demo-cli",
                        "description": "Demo external CLI",
                        "homepage": "https://example.com/demo",
                        "tags": ["demo", "github"],
                    }
                )
            }
        )

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://api.github.com/repos/acme/demo-cli":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/demo-cli/zipball/main":
                return _FakeBytesResponse(repo_zip)
            raise AssertionError(f"Unexpected URL: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch("advai.cli_manager.CLIS_DIR", temp_dir):
                with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    with mock.patch(
                        "advai.cli_manager.run_manager_command",
                        return_value={"stdout": "", "stderr": "", "returncode": 0},
                    ) as run_mock:
                        installed = install_github_clis("https://github.com/acme/demo-cli")

        self.assertEqual(installed[0]["name"], "demo-cli")
        self.assertEqual(installed[0]["binary"], "demo")
        run_mock.assert_called_once_with(
            [
                "opencli",
                "external",
                "register",
                "demo-cli",
                "--binary",
                "demo",
                "--install",
                "brew install demo-cli",
                "--desc",
                "Demo external CLI",
            ]
        )

    def test_list_github_repo_clis_reads_root_clis_directory(self):
        repo_zip = self._build_repo_zip(
            {
                "clis/alpha/cli.json": json.dumps({"name": "alpha"}),
                "clis/beta/cli.json": json.dumps({"name": "beta"}),
            }
        )

        def fake_urlopen(request, timeout=30):
            _ = timeout
            url = request.full_url if hasattr(request, "full_url") else request
            if url == "https://api.github.com/repos/acme/demo-cli":
                return _FakeResponse({"default_branch": "main"})
            if url == "https://api.github.com/repos/acme/demo-cli/zipball/main":
                return _FakeBytesResponse(repo_zip)
            raise AssertionError(f"Unexpected URL: {url}")

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            available = list_github_repo_clis("https://github.com/acme/demo-cli")

        self.assertEqual(available, ["alpha", "beta"])


class SkillCliInstallTests(unittest.TestCase):
    def test_cli_skill_install_rejects_non_github_input(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["skill", "install", "demo-skill"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(
            "Unable to determine skill source",
            result.output,
        )

    def test_cli_prompts_to_install_all_skills_from_multi_skill_repo(self):
        runner = CliRunner()
        with mock.patch(
            "advai.cli.list_github_repo_skills",
            return_value=["alpha", "beta"],
        ), mock.patch(
            "advai.cli.install_github_skills",
            return_value=[{"name": "alpha"}, {"name": "beta"}],
        ) as install_mock:
            result = runner.invoke(
                cli,
                ["skill", "install", "https://github.com/acme/demo-skill"],
                input="y\n",
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Repository skills:", result.output)
        self.assertIn("alpha", result.output)
        self.assertIn("beta", result.output)
        self.assertIn("Install all of them?", result.output)
        self.assertIn("Skill 'alpha' installed successfully", result.output)
        self.assertIn("Skill 'beta' installed successfully", result.output)
        install_mock.assert_called_once_with(
            "https://github.com/acme/demo-skill",
            force=False,
        )

    def test_cli_cancels_when_user_declines_multi_skill_install(self):
        runner = CliRunner()
        with mock.patch(
            "advai.cli.list_github_repo_skills",
            return_value=["alpha", "beta"],
        ), mock.patch("advai.cli.install_github_skills") as install_mock:
            result = runner.invoke(
                cli,
                ["skill", "install", "https://github.com/acme/demo-skill"],
                input="n\n",
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Installation cancelled.", result.output)
        install_mock.assert_not_called()

    def test_cli_skill_search_prints_results(self):
        runner = CliRunner()
        fake_result = mock.Mock()
        fake_result.name = "find-skills"
        fake_result.provider = "skills_sh"
        fake_result.version = None
        fake_result.description = ""
        with mock.patch("advai.cli.search_skills", return_value=[fake_result]):
            result = runner.invoke(cli, ["skill", "search", "find"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Skills:", result.output)
        self.assertIn("find-skills [skills_sh] unknown", result.output)

    def test_cli_skill_install_supports_skills_sh_name_with_source(self):
        runner = CliRunner()
        fake_result = mock.Mock()
        fake_result.name = "find-skills"
        fake_result.provider = "skills_sh"
        fake_result.install_spec = "skills.sh:vercel-labs/skills/find-skills"
        fake_result.homepage = "https://skills.sh/vercel-labs/skills/find-skills"
        with mock.patch(
            "advai.cli.search_skills",
            return_value=[fake_result],
        ), mock.patch(
            "advai.cli.install_skill",
            return_value={"name": "find-skills"},
        ) as install_mock:
            result = runner.invoke(
                cli,
                ["skill", "install", "find-skills", "--source", "skills_sh"],
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Skill 'find-skills' installed successfully", result.output)
        install_mock.assert_called_once()

    def test_cli_skill_install_prompts_for_skills_sh_search_choice(self):
        runner = CliRunner()
        result_a = mock.Mock()
        result_a.name = "find-skills"
        result_a.provider = "skills_sh"
        result_a.install_spec = "skills.sh:vercel-labs/skills/find-skills"
        result_a.homepage = "https://skills.sh/vercel-labs/skills/find-skills"
        result_b = mock.Mock()
        result_b.name = "find-skills"
        result_b.provider = "skills_sh"
        result_b.install_spec = "skills.sh:acme/skills/find-skills"
        result_b.homepage = "https://skills.sh/acme/skills/find-skills"
        with mock.patch(
            "advai.cli.search_skills",
            return_value=[result_a, result_b],
        ), mock.patch(
            "advai.cli.install_skill",
            return_value={"name": "find-skills"},
        ) as install_mock:
            result = runner.invoke(
                cli,
                ["skill", "install", "find-skills", "--source", "skills_sh"],
                input="2\n",
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Search results:", result.output)
        self.assertIn("Choose a skill number", result.output)
        install_mock.assert_called_once()
        self.assertEqual(
            install_mock.call_args.kwargs["source"],
            "skills_sh",
        )
        self.assertEqual(
            install_mock.call_args.args[0],
            "skills.sh:acme/skills/find-skills",
        )

    def test_cli_skill_install_skills_sh_yes_rejects_ambiguous_results(self):
        runner = CliRunner()
        result_a = mock.Mock()
        result_a.name = "find-skills"
        result_a.provider = "skills_sh"
        result_a.install_spec = "skills.sh:vercel-labs/skills/find-skills"
        result_a.homepage = "https://skills.sh/vercel-labs/skills/find-skills"
        result_b = mock.Mock()
        result_b.name = "find-skills"
        result_b.provider = "skills_sh"
        result_b.install_spec = "skills.sh:acme/skills/find-skills"
        result_b.homepage = "https://skills.sh/acme/skills/find-skills"
        with mock.patch(
            "advai.cli.search_skills",
            return_value=[result_a, result_b],
        ), mock.patch("advai.cli.install_skill") as install_mock:
            result = runner.invoke(
                cli,
                ["skill", "install", "find-skills", "--source", "skills_sh", "--yes"],
            )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Multiple skills found for 'find-skills'", result.output)
        install_mock.assert_not_called()

    def test_cli_install_github_repo_prompts_to_install_all_clis(self):
        runner = CliRunner()
        with mock.patch("advai.cli.opencli_available", return_value=True), mock.patch(
            "advai.cli.list_github_repo_clis",
            return_value=["alpha", "beta"],
        ), mock.patch(
            "advai.cli.install_github_clis",
            return_value=[{"name": "alpha"}, {"name": "beta"}],
        ) as install_mock:
            result = runner.invoke(
                cli,
                ["cli", "install", "https://github.com/acme/demo-cli"],
                input="y\n",
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Repository CLIs:", result.output)
        self.assertIn("alpha", result.output)
        self.assertIn("beta", result.output)
        self.assertIn("Multiple CLIs found. Install all of them?", result.output)
        self.assertIn("CLI 'alpha' install completed", result.output)
        self.assertIn("CLI 'beta' install completed", result.output)
        install_mock.assert_called_once_with("https://github.com/acme/demo-cli")

    def test_cli_cli_install_rejects_non_github_input(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["cli", "install", "demo-cli"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(
            "cli install currently only supports GitHub repository URLs",
            result.output,
        )


class ExternalCliCommandTests(unittest.TestCase):
    def test_cli_update_uses_opencli_external_update(self):
        runner = CliRunner()
        with mock.patch("advai.cli.opencli_available", return_value=True), mock.patch(
            "advai.cli.run_manager_command",
            return_value={"stdout": "", "stderr": "", "returncode": 0},
        ) as run_mock:
            result = runner.invoke(cli, ["cli", "update", "demo-cli", "--yes"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("CLI 'demo-cli' update completed", result.output)
        run_mock.assert_called_once_with(["opencli", "external", "update", "demo-cli"])

    def test_cli_uninstall_uses_opencli_external_uninstall(self):
        runner = CliRunner()
        with mock.patch("advai.cli.opencli_available", return_value=True), mock.patch(
            "advai.cli.run_manager_command",
            return_value={"stdout": "", "stderr": "", "returncode": 0},
        ) as run_mock:
            result = runner.invoke(cli, ["cli", "uninstall", "demo-cli", "--yes"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("CLI 'demo-cli' uninstall completed", result.output)
        run_mock.assert_called_once_with(["opencli", "external", "uninstall", "demo-cli"])

    def test_cli_list_reports_opencli_registry_errors_cleanly(self):
        runner = CliRunner()
        raw_error = """
        /Users/xuyi/.nvm/.../command.js:655
          throw new Error(
                ^

        Error: cannot add command 'zhihu' as already have command 'zhihu'
            at Command._registerCommand (/Users/xuyi/.nvm/.../command.js:655:13)

        Node.js v22.21.1
        """
        with mock.patch("advai.cli.opencli_available", return_value=True), mock.patch(
            "advai.cli.list_external_clis",
            side_effect=RuntimeError(raw_error),
        ):
            result = runner.invoke(cli, ["cli", "list"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("opencli failed while listing external CLIs", result.output)
        self.assertIn("cannot add command 'zhihu' as already have command 'zhihu'", result.output)
        self.assertNotIn("Node.js v22.21.1", result.output)
        self.assertNotIn("throw new Error", result.output)

    def test_dynamic_cli_resolution_reports_opencli_registry_errors_cleanly(self):
        runner = CliRunner()
        raw_error = """
        file:///dist/src/cli.js:3137
        Error: broken opencli registry
            at runCli (file:///dist/src/cli.js:3137:5)
        """
        with mock.patch("advai.cli.opencli_available", return_value=True), mock.patch(
            "advai.cli.cli_exists",
            side_effect=RuntimeError(raw_error),
        ):
            result = runner.invoke(cli, ["cli", "zhihu"])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("opencli failed while loading the CLI registry", result.output)
        self.assertIn("broken opencli registry", result.output)
        self.assertNotIn("file:///dist/src/cli.js", result.output)


if __name__ == "__main__":
    unittest.main()
