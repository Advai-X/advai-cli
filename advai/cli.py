import click
import os
import sys

from advai import __version__
from advai.skills import install_skill, uninstall_skill, list_skills, update_skill, info_skill

SKILLS_DIR = os.path.expanduser("~/.advai/skills")
CONFIG_DIR = os.path.expanduser("~/.advai")


def _ensure_dirs():
    os.makedirs(SKILLS_DIR, exist_ok=True)
    os.makedirs(CONFIG_DIR, exist_ok=True)


@click.group()
@click.version_option(version=__version__, prog_name="advai")
def cli():
    """advai — cross-platform AI Skill manager"""
    _ensure_dirs()


@cli.command()
@click.argument("skill_name")
@click.option("--force", is_flag=True, help="Force reinstall (overwrite existing)")
def install(skill_name, force):
    """Install a Skill: advai install <skill-name>"""
    try:
        install_skill(skill_name, force=force)
        click.echo(f"✅ Skill '{skill_name}' installed successfully")
    except FileExistsError:
        click.echo(f"⚠️  Skill '{skill_name}' already exists, use --force to overwrite")
    except Exception as e:
        click.echo(f"❌ Installation failed: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.argument("skill_name")
def uninstall(skill_name):
    """Uninstall a Skill: advai uninstall <skill-name>"""
    try:
        uninstall_skill(skill_name)
        click.echo(f"🗑️  Skill '{skill_name}' uninstalled")
    except FileNotFoundError:
        click.echo(f"⚠️  Skill '{skill_name}' is not installed")
    except Exception as e:
        click.echo(f"❌ Uninstall failed: {e}", err=True)
        sys.exit(1)


@cli.command(name="list")
def list_cmd():
    """List locally installed Skills"""
    skills = list_skills()
    if not skills:
        click.echo("(no Skills installed)")
        return
    click.echo("📋 Installed Skills:")
    for s in skills:
        click.echo(f"  • {s}")


@cli.command()
@click.argument("skill_name", required=False)
def update(skill_name):
    """Update one (or all) Skills: advai update [skill-name]"""
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


@cli.command()
@click.argument("skill_name")
def info(skill_name):
    """Show Skill details: advai info <skill-name>"""
    data = info_skill(skill_name)
    if data is None:
        click.echo(f"⚠️  Skill '{skill_name}' not installed or has no metadata")
        return
    click.echo(f"ℹ️  Skill '{skill_name}':")
    for k, v in data.items():
        click.echo(f"  {k}: {v}")


if __name__ == "__main__":
    cli()
