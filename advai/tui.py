from __future__ import annotations

import os
import select
import shutil
import sys
import termios
import textwrap
import tty
from datetime import datetime

import click

from advai import __version__
from advai.ai_client import (
    AIClientError,
    AIConfig,
    list_selectable_models,
    request_chat_completion,
)

HELP_TEXT = "Commands: /help /clear /model [name] /system <prompt> /save <path> /exit"
WELCOME_BANNER_ADVAI = (
    " █████╗ ██████╗ ██╗   ██╗ █████╗ ██╗      ██████╗██╗     ██╗",
    "██╔══██╗██╔══██╗██║   ██║██╔══██╗██║     ██╔════╝██║     ██║",
    "███████║██║  ██║██║   ██║███████║██║     ██║     ██║     ██║",
    "██╔══██║██║  ██║╚██╗ ██╔╝██╔══██║██║     ██║     ██║     ██║",
    "██║  ██║██████╔╝ ╚████╔╝ ██║  ██║██║     ╚██████╗███████╗██║",
    "╚═╝  ╚═╝╚═════╝   ╚═══╝  ╚═╝  ╚═╝╚═╝      ╚═════╝╚══════╝╚═╝",
)
WELCOME_TEXT = "Welcome to ADVAI-CLI.\nEnter a message to start chatting with the AI."
WELCOME_SUBTITLE = "Terminal AI Assistant"
ROLE_LABELS = {
    "user": "You",
    "assistant": "AI",
    "system": "System",
}


def parse_tui_command(value: str) -> tuple[str, str]:
    stripped = str(value or "").strip()
    if not stripped.startswith("/"):
        return "", ""
    parts = stripped[1:].split(None, 1)
    command = parts[0].lower() if parts and parts[0] else ""
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument


def _terminal_size() -> os.terminal_size:
    return shutil.get_terminal_size((100, 30))


def _format_message(role: str, content: str, width: int) -> list[str]:
    label = ROLE_LABELS.get(role, role.title() or "Message")
    prefix = f"{label}: "
    wrapped_lines = []

    for paragraph in str(content).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        wrapped = textwrap.wrap(
            paragraph,
            width=max(20, width - len(prefix)),
            replace_whitespace=False,
            drop_whitespace=False,
        )
        if not wrapped:
            wrapped = [""]
        for index, line in enumerate(wrapped):
            current_prefix = prefix if index == 0 else " " * len(prefix)
            wrapped_lines.append(f"{current_prefix}{line}")
    return wrapped_lines


def _render_transcript(history: list[dict], width: int, height: int) -> list[str]:
    lines = []
    for item in history:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if not role or not content:
            continue
        lines.extend(_format_message(role, content, width))
        lines.append("")
    if not lines:
        lines.append("(no messages yet)")
    return lines[-height:]


def _render_welcome_banner() -> None:
    click.echo()
    for line in WELCOME_BANNER_ADVAI:
        click.secho(line, fg="green")
    click.echo()
    click.secho(WELCOME_SUBTITLE, fg="bright_black", bold=True)
    click.secho(f"ADVAI-CLI v{__version__}", fg="bright_black")
    click.echo()


def _classify_picker_sequence(sequence: bytes) -> str:
    if sequence == b"\x03":
        return "interrupt"
    if sequence in {b"\r", b"\n"}:
        return "enter"
    if sequence == b"\x1b[A":
        return "up"
    if sequence == b"\x1b[B":
        return "down"
    if sequence.startswith(b"\x1b"):
        return "escape"
    return sequence.decode("utf-8", errors="ignore")


def _read_picker_key() -> str:
    fd = sys.stdin.fileno()
    previous = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        sequence = os.read(fd, 1)
        key = _classify_picker_sequence(sequence)
        if key == "interrupt":
            raise KeyboardInterrupt
        if key != "escape":
            return key

        while len(sequence) < 3:
            ready, _, _ = select.select([fd], [], [], 0.15)
            if not ready:
                break
            sequence += os.read(fd, 1)
            key = _classify_picker_sequence(sequence)
            if key in {"up", "down"}:
                return key

        key = _classify_picker_sequence(sequence)
        if key == "interrupt":
            raise KeyboardInterrupt
        return key
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, previous)


def _render_model_picker(models: list[str], selected_index: int, current_model: str) -> None:
    click.clear()
    click.echo()
    click.secho("Select a model", bold=True)
    click.echo("Use ↑/↓ to move, Enter to confirm, Esc to cancel.")
    click.echo()
    for index, model_name in enumerate(models):
        pointer = ">" if index == selected_index else " "
        suffix = " (current)" if model_name == current_model else ""
        if index == selected_index:
            click.secho(f"{pointer} {model_name}{suffix}", fg="green", bold=True)
        else:
            click.echo(f"{pointer} {model_name}{suffix}")
    click.echo()


def _select_model(current_model: str) -> str | None:
    models = list_selectable_models(current_model)
    selected_index = models.index(current_model) if current_model in models else 0

    while True:
        _render_model_picker(models, selected_index, current_model)
        try:
            key = _read_picker_key()
        except KeyboardInterrupt:
            return None

        if key == "up":
            selected_index = (selected_index - 1) % len(models)
            continue
        if key == "down":
            selected_index = (selected_index + 1) % len(models)
            continue
        if key == "enter":
            return models[selected_index]
        if key == "escape":
            return None


def _render_screen(config: AIConfig, history: list[dict], status: str, clear_screen: bool) -> None:
    if clear_screen:
        click.clear()

    size = _terminal_size()
    transcript_height = max(8, size.lines - 8)
    base_url = config.base_url.rstrip("/")
    transcript = _render_transcript(history, size.columns, transcript_height)

    if not history:
        _render_welcome_banner()
    click.echo(f"advai tui | model={config.model}")
    click.echo(f"backend={base_url}")
    click.echo(HELP_TEXT)
    click.echo("-" * min(size.columns, 80))
    for line in transcript:
        click.echo(line)
    click.echo("-" * min(size.columns, 80))
    click.echo(f"status: {status}")


def _save_transcript(history: list[dict], path: str, config: AIConfig) -> str:
    if not path:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = f"advai-chat-{timestamp}.md"

    resolved_path = os.path.realpath(os.path.expanduser(path))
    parent = os.path.dirname(resolved_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    lines = [
        "# advai tui transcript",
        "",
        f"- model: {config.model}",
        f"- base_url: {config.base_url}",
        "",
    ]
    for item in history:
        role = str(item.get("role") or "message").strip()
        content = str(item.get("content") or "").rstrip()
        if not content:
            continue
        lines.append(f"## {ROLE_LABELS.get(role, role.title())}")
        lines.append("")
        lines.append(content)
        lines.append("")

    with open(resolved_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")

    return resolved_path


def _handle_command(raw_value: str, history: list[dict], config: AIConfig) -> tuple[bool, str]:
    command, argument = parse_tui_command(raw_value)

    if command in {"exit", "quit"}:
        return False, "Session ended."
    if command == "help":
        return True, HELP_TEXT
    if command == "clear":
        history.clear()
        return True, "Conversation cleared."
    if command == "model":
        if not argument:
            selected_model = _select_model(config.model)
            if not selected_model:
                return True, f"Model selection cancelled. Current model: {config.model}"
            config.model = selected_model
            return True, f"Model switched to {config.model}"
        config.model = argument
        return True, f"Model switched to {config.model}"
    if command == "system":
        if not argument:
            return True, "Usage: /system <prompt>"
        config.system_prompt = argument
        return True, "System prompt updated for future turns."
    if command == "save":
        try:
            save_path = _save_transcript(history, argument, config)
        except OSError as exc:
            return True, f"Failed to save transcript: {exc}"
        return True, f"Transcript saved to {save_path}"
    if command == "":
        return True, "Usage: /help"

    return True, f"Unknown command /{command}. Type /help for commands."


def run_tui(config: AIConfig, clear_screen: bool = True) -> None:
    history: list[dict] = []
    status = WELCOME_TEXT

    while True:
        _render_screen(config, history, status, clear_screen=clear_screen)

        try:
            user_input = input("you> ").strip()
        except EOFError:
            click.echo()
            return
        except KeyboardInterrupt:
            click.echo()
            return

        if not user_input:
            status = "Please enter a message or type /help."
            continue

        if user_input.startswith("/"):
            should_continue, status = _handle_command(user_input, history, config)
            if not should_continue:
                if clear_screen:
                    click.clear()
                click.echo(status)
                return
            if status:
                continue

        history.append({"role": "user", "content": user_input})
        status = "Waiting for AI response..."
        _render_screen(config, history, status, clear_screen=clear_screen)

        try:
            response_text = request_chat_completion(config, history)
        except AIClientError as exc:
            status = str(exc)
            continue

        history.append({"role": "assistant", "content": response_text})
        status = "Response received."
