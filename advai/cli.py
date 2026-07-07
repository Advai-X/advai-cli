import base64
import json
import click
import os
import re
import sys

from advai import __version__
from advai.ai_client import AIClientError, load_ai_config
from advai.browser_bridge import (
    BrowserBridgeClient,
    BrowserBridgeError,
    DEFAULT_BROWSER_CONTEXT_ID,
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_PORT,
)
from advai.kb import (
    add_document,
    create_knowledge_base,
    search_knowledge_base,
    sync_knowledge_base,
)
from advai.skill_platforms import (
    add_custom_platform,
    clear_platform_override,
    list_skill_platforms,
    remove_custom_platform,
    resolve_platform_target,
    set_platform_override,
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
    list_skill_sync_targets,
    list_skills,
    sync_skill_to_platform,
    uninstall_skill,
    unsync_skill_from_platform,
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


def _sync_installed_skill_targets(skill_name, platforms, sync_mode, project_dir, force):
    synced = []
    for platform in platforms:
        synced.append(
            sync_skill_to_platform(
                skill_name,
                platform,
                project_dir=project_dir,
                mode=sync_mode,
                force=force,
            )
        )
    return synced


def _skill_install(
    skill_name,
    force,
    selected_skill=None,
    platforms=(),
    sync_mode="symlink",
    project_dir=None,
):
    try:
        if not skill_name.startswith("https://github.com/"):
            raise click.ClickException(
                "skill install currently only supports GitHub repository URLs"
            )
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
                    installed_name = metadata.get("name", "unknown")
                    _sync_installed_skill_targets(
                        installed_name,
                        platforms,
                        sync_mode,
                        project_dir,
                        force=force,
                    )
                    click.echo(
                        f"✅ Skill '{installed_name}' installed successfully"
                    )
                return

        metadata = install_skill(skill_name, force=force, selected_skill=selected_skill)
        installed_name = metadata.get("name", skill_name)
        _sync_installed_skill_targets(
            installed_name,
            platforms,
            sync_mode,
            project_dir,
            force=force,
        )
        click.echo(f"✅ Skill '{installed_name}' installed successfully")
    except FileExistsError:
        click.echo(f"⚠️  Skill '{skill_name}' already exists, use --force to overwrite")
    except Exception as e:
        click.echo(f"❌ Installation failed: {e}", err=True)
        sys.exit(1)


def _skill_uninstall(skill_name):
    try:
        sync_targets = list_skill_sync_targets(skill_name)
        uninstall_skill(skill_name)
        if sync_targets:
            click.echo(
                f"🗑️  Skill '{skill_name}' uninstalled and removed {len(sync_targets)} synced target(s)"
            )
        else:
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
        if k == "sync_targets":
            continue
        click.echo(f"  {k}: {v}")
    sync_targets = data.get("sync_targets") or []
    if not sync_targets:
        click.echo("  sync_targets: []")
        return
    click.echo("  sync_targets:")
    for target in sync_targets:
        project_dir = target.get("project_dir") or "-"
        click.echo(
            f"    - {target.get('platform')} | {target.get('mode')} | {target.get('path')} | project_dir={project_dir}"
        )


def _skill_sync(skill_name, platforms, sync_mode, project_dir, force):
    try:
        for platform in platforms:
            result = sync_skill_to_platform(
                skill_name,
                platform,
                project_dir=project_dir,
                mode=sync_mode,
                force=force,
            )
            click.echo(
                f"🔗 Skill '{skill_name}' synced to {result['platform']['display_name']} at {result['path']}"
            )
    except FileNotFoundError:
        click.echo(f"⚠️  Skill '{skill_name}' is not installed")
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Sync failed: {e}", err=True)
        sys.exit(1)


def _skill_unsync(skill_name, platforms, project_dir):
    try:
        for platform in platforms:
            result = unsync_skill_from_platform(
                skill_name,
                platform,
                project_dir=project_dir,
            )
            click.echo(
                f"🧹 Skill '{skill_name}' removed from {result['platform']['display_name']}"
            )
    except FileNotFoundError as e:
        click.echo(f"⚠️  {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Unsync failed: {e}", err=True)
        sys.exit(1)


def _skill_platform_list(project_dir):
    platforms = list_skill_platforms()
    if not platforms:
        click.echo("(no skill platforms configured)")
        return
    click.echo("Skill platforms:")
    for platform in platforms:
        target = resolve_platform_target(platform["key"], project_dir=project_dir)
        scope = "project" if target.get("project_dir") else "global"
        custom = "custom" if platform.get("is_custom") else "built-in"
        click.echo(
            f"  • {platform['display_name']} [{platform['key']}] ({platform['category']}, {custom}, {scope})"
        )
        click.echo(f"    skills_dir: {target['skills_dir']}")
        if platform.get("project_relative_skills_dir"):
            click.echo(
                f"    project_relative_skills_dir: {platform['project_relative_skills_dir']}"
            )


def _skill_platform_add(key, display_name, skills_dir, category, project_relative_skills_dir):
    try:
        platform = add_custom_platform(
            key,
            display_name,
            skills_dir,
            category=category,
            project_relative_skills_dir=project_relative_skills_dir,
        )
        click.echo(
            f"✅ Added custom platform '{platform['display_name']}' [{platform['key']}]"
        )
    except Exception as e:
        click.echo(f"❌ Adding platform failed: {e}", err=True)
        sys.exit(1)


def _skill_platform_remove(key):
    try:
        remove_custom_platform(key)
        click.echo(f"🗑️  Removed custom platform '{key}'")
    except Exception as e:
        click.echo(f"❌ Removing platform failed: {e}", err=True)
        sys.exit(1)


def _skill_platform_override(key, skills_dir, project_relative_skills_dir):
    try:
        platform = set_platform_override(
            key,
            skills_dir=skills_dir,
            project_relative_skills_dir=project_relative_skills_dir,
        )
        click.echo(
            f"✅ Updated platform '{platform['display_name']}' [{platform['key']}]"
        )
    except Exception as e:
        click.echo(f"❌ Updating platform override failed: {e}", err=True)
        sys.exit(1)


def _skill_platform_clear_override(key, clear_path, clear_project_path):
    try:
        platform = clear_platform_override(
            key,
            clear_skills_dir=clear_path,
            clear_project_relative_skills_dir=clear_project_path,
        )
        click.echo(
            f"✅ Cleared overrides for platform '{platform['display_name']}' [{platform['key']}]"
        )
    except Exception as e:
        click.echo(f"❌ Clearing platform override failed: {e}", err=True)
        sys.exit(1)


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


def _browser_client_from_context(ctx) -> BrowserBridgeClient:
    browser_client = (ctx.obj or {}).get("browser_client")
    if browser_client is None:
        raise click.ClickException("Browser client is not initialized")
    return browser_client


def _raise_browser_error(exc: BrowserBridgeError) -> None:
    message = str(exc)
    if exc.hint:
        message = f"{message}\nHint: {exc.hint}"
    raise click.ClickException(message) from exc


def _browser_print_result(data):
    if data is None:
        return
    if isinstance(data, (dict, list)):
        click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    else:
        click.echo(data)


def _browser_send(ctx, action, **payload):
    client = _browser_client_from_context(ctx)
    try:
        return client.send_command(action, **payload)
    except BrowserBridgeError as exc:
        _raise_browser_error(exc)


def _read_stdin_code(code: str) -> str:
    if code == "-":
        return sys.stdin.read()
    return code


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


@cli.group(name="browser")
@click.option(
    "--host",
    default=DEFAULT_DAEMON_HOST,
    envvar="ADVAI_BROWSER_HOST",
    show_default=True,
    help="Browser bridge daemon host",
)
@click.option(
    "--port",
    default=DEFAULT_DAEMON_PORT,
    envvar="ADVAI_BROWSER_PORT",
    show_default=True,
    type=int,
    help="Browser bridge daemon port",
)
@click.pass_context
def browser_admin(ctx, host, port):
    """Control a Chrome extension-backed browser bridge."""
    ctx.ensure_object(dict)
    ctx.obj["browser_client"] = BrowserBridgeClient(
        host=host,
        port=port,
        context_id=DEFAULT_BROWSER_CONTEXT_ID,
    )


@browser_admin.command(name="doctor")
@click.pass_context
def browser_doctor_cmd(ctx):
    """Check browser bridge connectivity."""
    client = _browser_client_from_context(ctx)
    daemon_running = client.ping_daemon()
    click.echo("Browser bridge:")
    click.echo(f"  host: {client.host}")
    click.echo(f"  port: {client.port}")
    click.echo(f"  daemon_running: {'yes' if daemon_running else 'no'}")
    click.echo(f"  context_id: {client.context_id or '-'}")
    click.echo(f"  daemon_log: {client.daemon_log_path}")
    click.echo(f"  daemon_pid: {client.daemon_pid_path}")
    if not daemon_running:
        if client.can_start_daemon():
            click.echo("  note: daemon can auto-start when a browser command runs")
        else:
            click.echo(
                "  note: start `python -m advai.browser_daemon` to enable browser commands"
            )
        return
    try:
        extensions = client.list_extensions()
    except BrowserBridgeError as exc:
        _raise_browser_error(exc)
        return
    click.echo(f"  connected_extensions: {len(extensions)}")
    if not extensions:
        click.echo(
            "  note: no browser extension is connected right now; open the extension popup or wait for it to reconnect"
        )
    for extension in extensions:
        selected = " [selected]" if client.context_id and extension.get("contextId") == client.context_id else ""
        click.echo(
            f"    - {extension.get('contextId')} (v{extension.get('version', '?')}){selected}"
        )


@browser_admin.command(name="extensions")
@click.pass_context
def browser_extensions_cmd(ctx):
    """List connected browser extension contexts."""
    client = _browser_client_from_context(ctx)
    try:
        _browser_print_result(client.list_extensions())
    except BrowserBridgeError as exc:
        _raise_browser_error(exc)


@browser_admin.command(name="open")
@click.argument("session")
@click.argument("url")
@click.option(
    "--window",
    "window_mode",
    type=click.Choice(["foreground", "background"], case_sensitive=False),
    default=None,
    help="Window mode for a new session window",
)
@click.option(
    "--replace",
    is_flag=True,
    help="Reuse the current tab when the session already has one",
)
@click.pass_context
def browser_open_cmd(ctx, session, url, window_mode, replace):
    """Open a URL in a browser session."""
    if replace and window_mode is not None:
        raise click.ClickException("`--replace` cannot be used together with `--window`.")

    if replace:
        client = _browser_client_from_context(ctx)
        try:
            result = client.send_command(
                "navigate",
                session=session,
                url=url,
                page=None,
            )
        except BrowserBridgeError as exc:
            if exc.code != "no_target":
                _raise_browser_error(exc)
            try:
                result = client.send_command(
                    "tabs",
                    session=session,
                    op="new",
                    url=url,
                    windowMode=None,
                )
            except BrowserBridgeError as fallback_exc:
                _raise_browser_error(fallback_exc)
    else:
        result = _browser_send(
            ctx,
            "tabs",
            session=session,
            op="new",
            url=url,
            windowMode=window_mode.lower() if window_mode else None,
        )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="navigate")
@click.argument("session")
@click.argument("url")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_navigate_cmd(ctx, session, url, page):
    """Navigate the current page."""
    result = _browser_send(ctx, "navigate", session=session, url=url, page=page)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="state")
@click.argument("session")
@click.pass_context
def browser_state_cmd(ctx, session):
    """Show the current browser session state."""
    result = _browser_send(ctx, "state", session=session)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="exec")
@click.argument("session")
@click.argument("code")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_exec_cmd(ctx, session, code, page):
    """Execute JavaScript in the current page."""
    result = _browser_send(
        ctx,
        "exec",
        session=session,
        code=_read_stdin_code(code),
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="click")
@click.argument("session")
@click.argument("selector")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_click_cmd(ctx, session, selector, page):
    """Click an element."""
    result = _browser_send(
        ctx,
        "click",
        session=session,
        selector=selector,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="type")
@click.argument("session")
@click.argument("selector")
@click.argument("value")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_type_cmd(ctx, session, selector, value, page):
    """Type text into an input."""
    result = _browser_send(
        ctx,
        "fill",
        session=session,
        selector=selector,
        value=value,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="fill")
@click.argument("session")
@click.argument("selector")
@click.argument("value")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_fill_cmd(ctx, session, selector, value, page):
    """Fill an input field."""
    result = _browser_send(
        ctx,
        "fill",
        session=session,
        selector=selector,
        value=value,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="select")
@click.argument("session")
@click.argument("selector")
@click.argument("option")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_select_cmd(ctx, session, selector, option, page):
    """Select an option."""
    result = _browser_send(
        ctx,
        "select",
        session=session,
        selector=selector,
        option=option,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="keys")
@click.argument("session")
@click.argument("text")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_keys_cmd(ctx, session, text, page):
    """Send keystrokes to the page."""
    result = _browser_send(ctx, "keys", session=session, text=text, page=page)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="wait")
@click.argument("session")
@click.option("--selector", default=None, help="Wait until a selector exists")
@click.option("--text", default=None, help="Wait until the page contains text")
@click.option("--timeout", default=10000, show_default=True, type=int, help="Wait timeout in milliseconds")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_wait_cmd(ctx, session, selector, text, timeout, page):
    """Wait for a selector, text, or a fixed delay."""
    result = _browser_send(
        ctx,
        "wait",
        session=session,
        selector=selector,
        text=text,
        page=page,
        waitFor="selector" if selector else ("text" if text else None),
        timeout=timeout,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="get")
@click.argument("session")
@click.option("--selector", default=None, help="Read one element instead of the whole page")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_get_cmd(ctx, session, selector, page):
    """Get page or element details."""
    result = _browser_send(
        ctx,
        "get",
        session=session,
        selector=selector,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="find")
@click.argument("session")
@click.argument("selector")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_find_cmd(ctx, session, selector, page):
    """Find all matching elements."""
    result = _browser_send(
        ctx,
        "find",
        session=session,
        selector=selector,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="extract")
@click.argument("session")
@click.argument("code", required=False, default=None)
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_extract_cmd(ctx, session, code, page):
    """Extract structured data with optional JavaScript."""
    result = _browser_send(
        ctx,
        "extract",
        session=session,
        code=_read_stdin_code(code) if code else None,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="screenshot")
@click.argument("session")
@click.option(
    "--format",
    "image_format",
    type=click.Choice(["png", "jpeg"], case_sensitive=False),
    default="png",
    show_default=True,
    help="Screenshot format",
)
@click.option("--full-page", is_flag=True, help="Capture the full page")
@click.option("--width", type=int, default=None, help="Override viewport width")
@click.option("--height", type=int, default=None, help="Override viewport height")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.option("--output", type=click.Path(path_type=str), default=None, help="Write decoded image bytes to a file")
@click.pass_context
def browser_screenshot_cmd(ctx, session, image_format, full_page, width, height, page, output):
    """Capture a screenshot."""
    result = _browser_send(
        ctx,
        "screenshot",
        session=session,
        page=page,
        format=image_format.lower(),
        fullPage=full_page,
        width=width,
        height=height,
    )
    screenshot_data = result.get("data")
    if output:
        with open(output, "wb") as handle:
            handle.write(base64.b64decode(screenshot_data))
        click.echo(f"Saved to {output}")
        return
    _browser_print_result(screenshot_data)


@browser_admin.command(name="cookies")
@click.argument("session")
@click.option("--domain", default=None, help="Filter cookies by domain")
@click.pass_context
def browser_cookies_cmd(ctx, session, domain):
    """List cookies."""
    result = _browser_send(ctx, "cookies", session=session, domain=domain)
    _browser_print_result(result.get("data"))


@browser_admin.group(name="tabs")
def browser_tabs_admin():
    """Manage tabs inside a browser session."""


@browser_tabs_admin.command(name="list")
@click.argument("session")
@click.pass_context
def browser_tabs_list_cmd(ctx, session):
    """List tabs."""
    result = _browser_send(ctx, "tabs", session=session, op="list")
    _browser_print_result(result.get("data"))


@browser_tabs_admin.command(name="new")
@click.argument("session")
@click.option("--url", default=None, help="Optional URL to open")
@click.pass_context
def browser_tabs_new_cmd(ctx, session, url):
    """Open a new tab."""
    result = _browser_send(ctx, "tabs", session=session, op="new", url=url)
    _browser_print_result(result.get("data"))


@browser_tabs_admin.command(name="select")
@click.argument("session")
@click.argument("index", type=int)
@click.pass_context
def browser_tabs_select_cmd(ctx, session, index):
    """Switch to a tab by index."""
    result = _browser_send(ctx, "tabs", session=session, op="select", index=index)
    _browser_print_result(result.get("data"))


@browser_tabs_admin.command(name="close")
@click.argument("session")
@click.argument("index", type=int)
@click.pass_context
def browser_tabs_close_cmd(ctx, session, index):
    """Close a tab by index."""
    result = _browser_send(ctx, "tabs", session=session, op="close", index=index)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="scroll")
@click.argument("session")
@click.option("--selector", default=None, help="Scroll an element into view")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_scroll_cmd(ctx, session, selector, page):
    """Scroll the page or a matching element."""
    result = _browser_send(
        ctx,
        "scroll",
        session=session,
        selector=selector,
        page=page,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="back")
@click.argument("session")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_back_cmd(ctx, session, page):
    """Go back in browser history."""
    result = _browser_send(ctx, "back", session=session, page=page)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="close")
@click.argument("session")
@click.pass_context
def browser_close_cmd(ctx, session):
    """Close a browser session."""
    result = _browser_send(ctx, "close", session=session)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="cdp")
@click.argument("session")
@click.argument("method")
@click.option("--params", default=None, help="JSON object passed to the CDP method")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_cdp_cmd(ctx, session, method, params, page):
    """Execute a raw CDP command."""
    parsed_params = json.loads(params) if params else None
    result = _browser_send(
        ctx,
        "cdp",
        session=session,
        page=page,
        cdpMethod=method,
        cdpParams=parsed_params,
    )
    _browser_print_result(result.get("data"))


@browser_admin.group(name="network")
def browser_network_admin():
    """Capture browser network activity."""


@browser_network_admin.command(name="start")
@click.argument("session")
@click.option("--pattern", default=None, help="Only capture matching request URLs")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_network_start_cmd(ctx, session, pattern, page):
    """Start capturing network requests."""
    result = _browser_send(
        ctx,
        "network-capture-start",
        session=session,
        page=page,
        pattern=pattern,
    )
    _browser_print_result(result.get("data"))


@browser_network_admin.command(name="read")
@click.argument("session")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_network_read_cmd(ctx, session, page):
    """Read captured network requests."""
    result = _browser_send(ctx, "network-capture-read", session=session, page=page)
    _browser_print_result(result.get("data"))


@browser_admin.command(name="download")
@click.argument("session")
@click.option("--pattern", default="", show_default=True, help="Only match download filenames containing this text")
@click.option("--timeout", default=30000, show_default=True, type=int, help="Download wait timeout in milliseconds")
@click.pass_context
def browser_download_cmd(ctx, session, pattern, timeout):
    """Wait for a download to complete."""
    result = _browser_send(
        ctx,
        "wait-download",
        session=session,
        pattern=pattern,
        timeoutMs=timeout,
        timeout=timeout,
    )
    _browser_print_result(result.get("data"))


@browser_admin.command(name="frames")
@click.argument("session")
@click.option("--page", default=None, help="Target page or tab identifier")
@click.pass_context
def browser_frames_cmd(ctx, session, page):
    """List page frames."""
    result = _browser_send(ctx, "frames", session=session, page=page)
    _browser_print_result(result.get("data"))


@cli.group(name="skill")
def skill_admin():
    """Manage skills."""


@skill_admin.command(name="install")
@click.argument("skill_name")
@click.option("--force", is_flag=True, help="Force reinstall (overwrite existing)")
@click.option("--skill", "selected_skill", default=None, help="Select one skill from a GitHub repo's skills directory")
@click.option(
    "--platform",
    "platforms",
    multiple=True,
    help="Sync the installed skill to one or more target platforms",
)
@click.option(
    "--sync-mode",
    type=click.Choice(["symlink", "copy"], case_sensitive=False),
    default="symlink",
    show_default=True,
    help="How synced skills are written to platform directories",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=str),
    default=None,
    help="Use a project-local platform skills path when the platform supports it",
)
def skill_install_cmd(skill_name, force, selected_skill, platforms, sync_mode, project_dir):
    """Install a Skill."""
    _skill_install(
        skill_name,
        force,
        selected_skill=selected_skill,
        platforms=platforms,
        sync_mode=sync_mode.lower(),
        project_dir=project_dir,
    )


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


@skill_admin.command(name="sync")
@click.argument("skill_name")
@click.option(
    "--platform",
    "platforms",
    multiple=True,
    required=True,
    help="Target platform key, repeat for multiple platforms",
)
@click.option(
    "--sync-mode",
    type=click.Choice(["symlink", "copy"], case_sensitive=False),
    default="symlink",
    show_default=True,
    help="How synced skills are written to platform directories",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=str),
    default=None,
    help="Use a project-local platform skills path when the platform supports it",
)
@click.option("--force", is_flag=True, help="Overwrite an existing target path")
def skill_sync_cmd(skill_name, platforms, sync_mode, project_dir, force):
    """Sync a locally installed skill to one or more platforms."""
    _skill_sync(skill_name, platforms, sync_mode.lower(), project_dir, force)


@skill_admin.command(name="unsync")
@click.argument("skill_name")
@click.option(
    "--platform",
    "platforms",
    multiple=True,
    required=True,
    help="Target platform key, repeat for multiple platforms",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=str),
    default=None,
    help="Remove the project-local sync target for a platform",
)
def skill_unsync_cmd(skill_name, platforms, project_dir):
    """Remove synced platform targets for a skill."""
    _skill_unsync(skill_name, platforms, project_dir)


@skill_admin.group(name="platform")
def skill_platform_admin():
    """Manage skill platforms and path overrides."""


@skill_platform_admin.command(name="list")
@click.option(
    "--project-dir",
    type=click.Path(path_type=str),
    default=None,
    help="Resolve platform paths for a specific project directory when supported",
)
def skill_platform_list_cmd(project_dir):
    """List supported skill platforms."""
    _skill_platform_list(project_dir)


@skill_platform_admin.command(name="add")
@click.argument("key")
@click.option("--name", "display_name", required=True, help="Platform display name")
@click.option("--path", "skills_dir", required=True, help="Global skills directory path")
@click.option(
    "--category",
    type=click.Choice(["coding", "lobster", "custom"], case_sensitive=False),
    default="custom",
    show_default=True,
    help="Platform category label",
)
@click.option(
    "--project-path",
    "project_relative_skills_dir",
    default=None,
    help="Optional project-relative skills directory",
)
def skill_platform_add_cmd(key, display_name, skills_dir, category, project_relative_skills_dir):
    """Add a custom skill platform."""
    _skill_platform_add(
        key,
        display_name,
        skills_dir,
        category.lower(),
        project_relative_skills_dir,
    )


@skill_platform_admin.command(name="remove")
@click.argument("key")
def skill_platform_remove_cmd(key):
    """Remove a custom skill platform."""
    _skill_platform_remove(key)


@skill_platform_admin.command(name="override")
@click.argument("key")
@click.option("--path", "skills_dir", default=None, help="Override the global skills directory")
@click.option(
    "--project-path",
    "project_relative_skills_dir",
    default=None,
    help="Override the project-relative skills directory",
)
def skill_platform_override_cmd(key, skills_dir, project_relative_skills_dir):
    """Override a built-in or custom platform path."""
    _skill_platform_override(key, skills_dir, project_relative_skills_dir)


@skill_platform_admin.command(name="clear-override")
@click.argument("key")
@click.option(
    "--keep-path",
    is_flag=True,
    help="Do not clear the global skills directory override",
)
@click.option(
    "--keep-project-path",
    is_flag=True,
    help="Do not clear the project-relative skills directory override",
)
def skill_platform_clear_override_cmd(key, keep_path, keep_project_path):
    """Clear built-in platform path overrides."""
    _skill_platform_clear_override(key, not keep_path, not keep_project_path)


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
@click.option("--cli", "selected_cli", default=None, help="Select one CLI from a GitHub repo's clis directory")
def cli_install_cmd(cli_name, selected_cli):
    """Install an external CLI."""
    if not looks_like_github_url(cli_name):
        raise click.ClickException(
            "cli install currently only supports GitHub repository URLs"
        )

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
