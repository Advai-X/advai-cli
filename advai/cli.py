import click
import os
import re
import sys

from advai import __version__
from advai.ai_client import AIClientError, load_ai_config
from advai.kb import (
    add_document,
    create_knowledge_base,
    search_knowledge_base,
    sync_knowledge_base,
)
from advai.cli_manager import (
    cli_info,
    install_github_clis,
    get_available_cli_info,
    list_external_clis,
    list_github_repo_clis,
    looks_like_github_url,
    get_external_cli_info,
    cli_exists,
    build_cli_exec_command,
    build_external_cli_install_command,
    build_external_cli_uninstall_command,
    build_external_cli_update_command,
    opencli_available,
    build_recommended_update_command,
    run_manager_command,
    run_passthrough_command,
)
from advai.skills import (
    info_skill,
    install_github_skills,
    install_skill,
    list_github_repo_skills,
    list_skills,
    uninstall_skill,
    update_skill,
)
from advai.tui import run_tui

SKILLS_DIR = os.path.expanduser("~/.advai/skills")
CLIS_DIR = os.path.expanduser("~/.advai/clis")
KBS_DIR = os.path.expanduser("~/.advai/kbs")
CONFIG_DIR = os.path.expanduser("~/.advai")


def _safe_makedirs(path):
    try:
        os.makedirs(path, exist_ok=True)
    except PermissionError:
        # Defer write failures to the specific command that actually needs the path.
        return


def _ensure_dirs():
    _safe_makedirs(SKILLS_DIR)
    _safe_makedirs(CLIS_DIR)
    _safe_makedirs(KBS_DIR)
    _safe_makedirs(CONFIG_DIR)


@click.group()
@click.version_option(version=__version__, prog_name="advai")
def cli():
    """Manage skills and external CLIs."""
    _ensure_dirs()


class ExternalCLIGroup(click.Group):
    """Static management commands + dynamic OpenCLI proxy."""

    def get_command(self, ctx, cmd_name):
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        if not opencli_available():
            return None
        try:
            exists = cli_exists(cmd_name)
        except RuntimeError as exc:
            _raise_opencli_error("loading the CLI registry", exc)
        if not exists:
            return None

        @click.command(
            name=cmd_name,
            context_settings={
                "ignore_unknown_options": True,
                "allow_extra_args": True,
            },
            add_help_option=False,
        )
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        def dynamic_cli_cmd(args):
            exit_code = run_passthrough_command(build_cli_exec_command(cmd_name, list(args)))
            raise click.exceptions.Exit(exit_code)

        return dynamic_cli_cmd


def _raise_opencli_error(action: str, exc: Exception) -> None:
    raise click.ClickException(
        f"opencli failed while {action}: {_summarize_opencli_error(exc)}"
    ) from exc


def _summarize_opencli_error(exc: Exception) -> str:
    raw_message = str(exc or "").strip()
    if not raw_message:
        return "unknown opencli error"

    lines = [line.strip() for line in raw_message.splitlines() if line.strip()]
    cleaned = [
        line
        for line in lines
        if not (
            line.startswith("at ")
            or line.startswith("throw new Error")
            or line.startswith("^")
            or line.startswith("Node.js v")
            or line.startswith("/Users/")
            or line.startswith("file://")
        )
    ]

    error_lines = [line for line in cleaned if line.startswith("Error:")]
    if error_lines:
        message = error_lines[-1].removeprefix("Error:").strip()
        return re.sub(r"\s+", " ", message)

    if cleaned:
        return re.sub(r"\s+", " ", cleaned[-1])

    return re.sub(r"\s+", " ", lines[-1])


def _skill_install(skill_name, force, selected_skill=None):
    try:
        if skill_name.startswith("https://github.com/") and not selected_skill:
            available_skills = list_github_repo_skills(skill_name)
            if len(available_skills) > 1:
                click.echo("Repository skills:")
                for name in available_skills:
                    click.echo(f"  - {name}")
                confirmed = click.confirm(
                    "Multiple skills found. Install all of them?",
                    default=False,
                )
                if not confirmed:
                    click.echo("Installation cancelled.")
                    return

                installed = install_github_skills(skill_name, force=force)
                for metadata in installed:
                    click.echo(
                        f"✅ Skill '{metadata.get('name', 'unknown')}' installed successfully"
                    )
                return

        metadata = install_skill(skill_name, force=force, selected_skill=selected_skill)
        installed_name = metadata.get("name", skill_name)
        click.echo(f"✅ Skill '{installed_name}' installed successfully")
    except FileExistsError:
        click.echo(f"⚠️  Skill '{skill_name}' already exists, use --force to overwrite")
    except Exception as e:
        click.echo(f"❌ Installation failed: {e}", err=True)
        sys.exit(1)


def _skill_uninstall(skill_name):
    try:
        uninstall_skill(skill_name)
        click.echo(f"🗑️  Skill '{skill_name}' uninstalled")
    except FileNotFoundError:
        click.echo(f"⚠️  Skill '{skill_name}' is not installed")
    except Exception as e:
        click.echo(f"❌ Uninstall failed: {e}", err=True)
        sys.exit(1)


def _skill_list():
    skills = list_skills()
    if not skills:
        click.echo("(no Skills installed)")
        return
    click.echo("📋 Installed Skills:")
    for s in skills:
        click.echo(f"  • {s}")


def _skill_update(skill_name, selected_skill=None):
    try:
        updated = update_skill(skill_name, selected_skill=selected_skill)
        if updated:
            for s in updated:
                click.echo(f"🔄 {s} updated")
        else:
            click.echo("(nothing to update)")
    except Exception as e:
        click.echo(f"❌ Update failed: {e}", err=True)
        sys.exit(1)


def _skill_info(skill_name):
    data = info_skill(skill_name)
    if data is None:
        click.echo(f"⚠️  Skill '{skill_name}' not installed or has no metadata")
        return
    click.echo(f"ℹ️  Skill '{skill_name}':")
    for k, v in data.items():
        click.echo(f"  {k}: {v}")


def _self_info():
    data = cli_info()
    click.echo("advai:")
    click.echo(f"  name: {data['name']}")
    click.echo(f"  version: {data['version']}")
    click.echo(f"  install_method: {data['install_method']}")
    click.echo(f"  python: {data['python']}")
    click.echo(f"  entry: {data['entry']}")
    click.echo(f"  module: {data['module']}")
    click.echo(f"  skills_dir: {data['skills_dir']}")
    click.echo("  available_managers:")
    for manager, available in data["available_managers"].items():
        click.echo(f"    {manager}: {'yes' if available else 'no'}")


@cli.command(name="info")
def self_info_cmd():
    """Show advai details."""
    _self_info()


@cli.command(name="update")
def self_update_cmd():
    """Show the recommended package-manager update command."""
    command = build_recommended_update_command()
    click.echo(f"Recommended update command: {' '.join(command)}")


@cli.command(name="tui")
@click.option("--agent", default=None, help="Override the AI agent name")
@click.option("--model", default=None, help="Override the AI model name")
@click.option("--base-url", default=None, help="Override the OpenAI-compatible API base URL")
@click.option("--system-prompt", default=None, help="Set the initial system prompt")
@click.option("--timeout", default=None, type=int, help="Request timeout in seconds")
@click.option("--no-clear", is_flag=True, help="Do not clear the terminal between turns")
def tui_cmd(agent, model, base_url, system_prompt, timeout, no_clear):
    """Start a terminal chat UI backed by an OpenAI-compatible API."""
    try:
        config = load_ai_config(
            agent=agent,
            model=model,
            base_url=base_url,
            system_prompt=system_prompt,
            timeout=timeout,
        )
        run_tui(config, clear_screen=not no_clear)
    except AIClientError as exc:
        raise click.ClickException(str(exc)) from exc


@cli.group(name="skill")
def skill_admin():
    """Manage skills."""


@skill_admin.command(name="install")
@click.argument("skill_name")
@click.option("--force", is_flag=True, help="Force reinstall (overwrite existing)")
@click.option("--skill", "selected_skill", default=None, help="Select one skill from a GitHub repo's skills directory")
def skill_install_cmd(skill_name, force, selected_skill):
    """Install a Skill."""
    _skill_install(skill_name, force, selected_skill=selected_skill)


@skill_admin.command(name="uninstall")
@click.argument("skill_name")
def skill_uninstall_cmd(skill_name):
    """Uninstall a Skill."""
    _skill_uninstall(skill_name)


@skill_admin.command(name="list")
def skill_list_cmd():
    """List locally installed Skills."""
    _skill_list()


@skill_admin.command(name="update")
@click.argument("skill_name", required=False)
@click.option("--skill", "selected_skill", default=None, help="Select one skill when updating from a GitHub repo URL")
def skill_update_cmd(skill_name, selected_skill):
    """Update one or all Skills."""
    _skill_update(skill_name, selected_skill=selected_skill)


@skill_admin.command(name="info")
@click.argument("skill_name")
def skill_info_cmd(skill_name):
    """Show Skill details."""
    _skill_info(skill_name)


@cli.group(name="kb")
def kb_admin():
    """Manage local knowledge bases."""


@kb_admin.command(name="create")
@click.argument("kb_name")
def kb_create_cmd(kb_name):
    """Create a knowledge base."""
    try:
        create_knowledge_base(kb_name)
    except FileExistsError as exc:
        raise click.ClickException(str(exc)) from exc
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"Knowledge base '{kb_name}' created")


@kb_admin.command(name="search")
@click.argument("kb_name")
@click.argument("query")
def kb_search_cmd(kb_name, query):
    """Search a knowledge base by keyword."""
    try:
        results = search_knowledge_base(kb_name, query)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if not results:
        click.echo(f"No matches found in knowledge base '{kb_name}'")
        return

    click.echo(f"Search results for '{query}' in '{kb_name}':")
    for item in results:
        click.echo(
            f"  - {item['document']}:{item['line_number']}: {item['line']}"
        )


@kb_admin.command(name="sync")
@click.argument("kb_name")
def kb_sync_cmd(kb_name):
    """Sync stored documents from their source files."""
    try:
        result = sync_knowledge_base(kb_name)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(
        f"Knowledge base '{kb_name}' synced: {result['synced']}/{result['document_count']} documents updated"
    )
    if result["missing"]:
        click.echo("Missing source files:")
        for path in result["missing"]:
            click.echo(f"  - {path}")


@kb_admin.group(name="doc")
def kb_doc_admin():
    """Manage knowledge base documents."""


@kb_doc_admin.command(name="add")
@click.argument("kb_name")
@click.argument("document_path", type=click.Path(path_type=str))
def kb_doc_add_cmd(kb_name, document_path):
    """Add a document to a knowledge base."""
    try:
        document = add_document(kb_name, document_path)
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Added document '{document['display_name']}' to knowledge base '{kb_name}'"
    )


@cli.group(name="cli", cls=ExternalCLIGroup)
def cli_admin():
    """Manage or execute external CLIs."""


@cli_admin.command(name="info")
@click.argument("cli_name")
def cli_info_cmd(cli_name):
    """Show external CLI details."""
    try:
        external = get_external_cli_info(cli_name)
        available = get_available_cli_info(cli_name)
    except RuntimeError as exc:
        _raise_opencli_error("reading CLI info", exc)

    if external is not None:
        click.echo(f"CLI '{cli_name}':")
        for key in ("name", "package", "binary", "installed", "description", "homepage", "tags"):
            click.echo(f"  {key}: {external.get(key)}")
        return
    if available is not None:
        click.echo(f"CLI '{cli_name}':")
        click.echo("  source: opencli")
        click.echo(f"  command_count: {available['command_count']}")
        click.echo(f"  commands: {', '.join(available['commands'])}")
        if available.get("description"):
            click.echo(f"  description: {available['description']}")
        return
    raise click.ClickException(f"CLI '{cli_name}' was not found")


@cli_admin.command(name="list")
@click.option("--search", default="", help="Filter CLI names")
def cli_list_cmd(search):
    """List installable external CLIs."""
    if not opencli_available():
        raise click.ClickException("opencli is not installed or not on PATH")
    try:
        targets = list_external_clis(search)
    except RuntimeError as exc:
        _raise_opencli_error("listing external CLIs", exc)
    if not targets:
        click.echo("(no external CLIs found)")
        return
    click.echo("External CLIs:")
    for item in targets:
        installed = "installed" if item.get("installed") else "not installed"
        click.echo(f"  • {item['name']} ({installed})")
        if item.get("description"):
            click.echo(f"    description: {item['description']}")


def _execute_cli_command(command, action):
    try:
        result = run_manager_command(command)
    except RuntimeError as exc:
        _raise_opencli_error(f"{action} the external CLI", exc)
    if result["stdout"]:
        click.echo(result["stdout"])
    if result["returncode"] != 0:
        if result["stderr"]:
            click.echo(result["stderr"], err=True)
        raise click.ClickException(f"CLI {action} failed")
    if result["stderr"]:
        click.echo(result["stderr"])


@cli_admin.command(name="install")
@click.argument("cli_name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--cli", "selected_cli", default=None, help="Select one CLI from a GitHub repo's clis directory")
def cli_install_cmd(cli_name, yes, selected_cli):
    """Install an external CLI."""
    if looks_like_github_url(cli_name):
        if not opencli_available():
            raise click.ClickException("opencli is not installed or not on PATH")
        try:
            if selected_cli:
                installed = install_github_clis(cli_name, selected_clis=[selected_cli])
                for item in installed:
                    click.echo(f"CLI '{item['name']}' install completed")
                return

            available_clis = list_github_repo_clis(cli_name)
            if len(available_clis) > 1:
                click.echo("Repository CLIs:")
                for name in available_clis:
                    click.echo(f"  - {name}")
                confirmed = click.confirm(
                    "Multiple CLIs found. Install all of them?",
                    default=False,
                )
                if not confirmed:
                    click.echo("Installation cancelled.")
                    return
                installed = install_github_clis(cli_name)
                for item in installed:
                    click.echo(f"CLI '{item['name']}' install completed")
                return

            installed = install_github_clis(cli_name)
            for item in installed:
                click.echo(f"CLI '{item['name']}' install completed")
            return
        except RuntimeError as exc:
            _raise_opencli_error("installing GitHub external CLIs", exc)

    if selected_cli:
        raise click.ClickException("--cli can only be used with a GitHub repository URL")

    if not opencli_available():
        raise click.ClickException("opencli is not installed or not on PATH")
    command = build_external_cli_install_command(cli_name)
    if not yes:
        click.confirm(f"Install external CLI '{cli_name}' via: {' '.join(command)} ?", abort=True)
    _execute_cli_command(command, "install")
    click.echo(f"CLI '{cli_name}' install completed")


@cli_admin.command(name="update")
@click.argument("cli_name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def cli_update_cmd(cli_name, yes):
    """Update an external CLI."""
    if not opencli_available():
        raise click.ClickException("opencli is not installed or not on PATH")
    command = build_external_cli_update_command(cli_name)
    if not yes:
        click.confirm(f"Update external CLI '{cli_name}' via: {' '.join(command)} ?", abort=True)
    _execute_cli_command(command, "update")
    click.echo(f"CLI '{cli_name}' update completed")


@cli_admin.command(name="uninstall")
@click.argument("cli_name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
def cli_uninstall_cmd(cli_name, yes):
    """Uninstall an external CLI."""
    if not opencli_available():
        raise click.ClickException("opencli is not installed or not on PATH")
    command = build_external_cli_uninstall_command(cli_name)
    if not yes:
        click.confirm(
            f"Uninstall external CLI '{cli_name}' via: {' '.join(command)} ?",
            abort=True,
        )
    _execute_cli_command(command, "uninstall")
    click.echo(f"CLI '{cli_name}' uninstall completed")


if __name__ == "__main__":
    cli()
