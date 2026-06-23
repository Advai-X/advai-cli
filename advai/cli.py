import click
import os
import sys

from advai import __version__
from advai.cli_manager import (
    cli_info,
    get_available_cli_info,
    list_external_clis,
    get_external_cli_info,
    cli_exists,
    build_cli_exec_command,
    build_external_cli_install_command,
    opencli_available,
    build_recommended_update_command,
    run_manager_command,
    run_passthrough_command,
)
from advai.skills import install_skill, uninstall_skill, list_skills, update_skill, info_skill

SKILLS_DIR = os.path.expanduser("~/.advai/skills")
CONFIG_DIR = os.path.expanduser("~/.advai")


def _ensure_dirs():
    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)


@click.group()
@click.version_option(version=__version__, prog_name="advai")
def cli():
    """Manage AdvAI skills and external CLIs."""
    _ensure_dirs()


class ExternalCLIGroup(click.Group):
    """Static management commands + dynamic OpenCLI proxy."""

    def get_command(self, ctx, cmd_name):
        command = super().get_command(ctx, cmd_name)
        if command is not None:
            return command
        if not opencli_available():
            return None
        if not cli_exists(cmd_name):
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


def _skill_install(skill_name, force):
    try:
        install_skill(skill_name, force=force)
        click.echo(f"✅ Skill '{skill_name}' installed successfully")
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


def _skill_update(skill_name):
    try:
        updated = update_skill(skill_name)
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


@cli.group(name="skill")
def skill_admin():
    """Manage AdvAI skills."""


@skill_admin.command(name="install")
@click.argument("skill_name")
@click.option("--force", is_flag=True, help="Force reinstall (overwrite existing)")
def skill_install_cmd(skill_name, force):
    """Install a Skill."""
    _skill_install(skill_name, force)


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
def skill_update_cmd(skill_name):
    """Update one or all Skills."""
    _skill_update(skill_name)


@skill_admin.command(name="info")
@click.argument("skill_name")
def skill_info_cmd(skill_name):
    """Show Skill details."""
    _skill_info(skill_name)


@cli.group(name="cli", cls=ExternalCLIGroup)
def cli_admin():
    """Manage or execute external CLIs."""


@cli_admin.command(name="info")
@click.argument("cli_name")
def cli_info_cmd(cli_name):
    """Show external CLI details."""
    external = get_external_cli_info(cli_name)
    if external is not None:
        click.echo(f"CLI '{cli_name}':")
        for key in ("name", "package", "binary", "installed", "description", "homepage", "tags"):
            click.echo(f"  {key}: {external.get(key)}")
        return
    available = get_available_cli_info(cli_name)
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
    targets = list_external_clis(search)
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
    result = run_manager_command(command)
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
def cli_install_cmd(cli_name, yes):
    """Install an external CLI."""
    if not opencli_available():
        raise click.ClickException("opencli is not installed or not on PATH")
    command = build_external_cli_install_command(cli_name)
    if not yes:
        click.confirm(f"Install external CLI '{cli_name}' via: {' '.join(command)} ?", abort=True)
    _execute_cli_command(command, "install")
    click.echo(f"CLI '{cli_name}' install completed")


if __name__ == "__main__":
    cli()
