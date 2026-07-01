import os
import tempfile
import unittest

from advai import skill_platforms, skills


class SkillPlatformTests(unittest.TestCase):
    def _install_local_skill_fixture(self, skill_name: str) -> None:
        skill_path = os.path.join(skills.SKILLS_DIR, skill_name)
        os.makedirs(skill_path, exist_ok=True)
        with open(os.path.join(skill_path, "skill.json"), "w", encoding="utf-8") as handle:
            handle.write(
                '{"name": "%s", "version": "0.1.0", "status": "installed", "source": {"type": "fixture"}}'
                % skill_name
            )

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home_dir = self.temp_dir.name

        self.original_home = os.environ.get("HOME")
        self.original_skills_dir = skills.SKILLS_DIR
        self.original_config_dir = skills.CONFIG_DIR
        self.original_platform_config_dir = skill_platforms.CONFIG_DIR
        self.original_platform_config_path = skill_platforms.PLATFORM_CONFIG_PATH

        os.environ["HOME"] = self.home_dir
        skills.SKILLS_DIR = os.path.join(self.home_dir, ".advai", "skills")
        skills.CONFIG_DIR = os.path.join(self.home_dir, ".advai")
        skill_platforms.CONFIG_DIR = os.path.join(self.home_dir, ".advai")
        skill_platforms.PLATFORM_CONFIG_PATH = os.path.join(
            skill_platforms.CONFIG_DIR, "skill_platforms.json"
        )

        os.makedirs(skills.SKILLS_DIR, exist_ok=True)
        os.makedirs(skill_platforms.CONFIG_DIR, exist_ok=True)

    def tearDown(self):
        if self.original_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = self.original_home

        skills.SKILLS_DIR = self.original_skills_dir
        skills.CONFIG_DIR = self.original_config_dir
        skill_platforms.CONFIG_DIR = self.original_platform_config_dir
        skill_platforms.PLATFORM_CONFIG_PATH = self.original_platform_config_path
        self.temp_dir.cleanup()

    def test_builtin_platform_resolution_supports_global_and_project_dirs(self):
        cursor_target = skill_platforms.resolve_platform_target("cursor")
        self.assertEqual(
            cursor_target["skills_dir"],
            os.path.join(self.home_dir, ".cursor", "skills"),
        )
        self.assertIsNone(cursor_target["project_dir"])

        repo_dir = os.path.join(self.home_dir, "repo")
        os.makedirs(repo_dir, exist_ok=True)
        omp_target = skill_platforms.resolve_platform_target(
            "omp_agent",
            project_dir=repo_dir,
        )
        self.assertEqual(
            omp_target["skills_dir"],
            os.path.join(repo_dir, ".omp", "skills"),
        )
        self.assertEqual(omp_target["project_dir"], repo_dir)

    def test_sync_and_unsync_skill_updates_metadata_and_filesystem(self):
        self._install_local_skill_fixture("demo-skill")

        sync_result = skills.sync_skill_to_platform(
            "demo-skill",
            "cursor",
            mode="copy",
        )
        self.assertTrue(os.path.isdir(sync_result["path"]))

        metadata = skills.info_skill("demo-skill")
        self.assertEqual(len(metadata["sync_targets"]), 1)
        self.assertEqual(metadata["sync_targets"][0]["platform"], "cursor")

        unsync_result = skills.unsync_skill_from_platform("demo-skill", "cursor")
        self.assertEqual(len(unsync_result["removed"]), 1)
        self.assertFalse(os.path.exists(sync_result["path"]))
        self.assertEqual(skills.info_skill("demo-skill")["sync_targets"], [])

    def test_custom_platform_can_be_registered_and_synced(self):
        custom_path = os.path.join(self.home_dir, "custom-platform-skills")
        platform = skill_platforms.add_custom_platform(
            "demo_platform",
            "Demo Platform",
            custom_path,
        )
        self.assertEqual(platform["key"], "demo_platform")

        self._install_local_skill_fixture("demo-skill")
        sync_result = skills.sync_skill_to_platform("demo-skill", "demo_platform")
        self.assertTrue(os.path.islink(sync_result["path"]))
        self.assertEqual(
            os.path.realpath(sync_result["path"]),
            os.path.realpath(skills._skill_path("demo-skill")),
        )


if __name__ == "__main__":
    unittest.main()
