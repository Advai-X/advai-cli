from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TUI_MODELS = (
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1-mini",
    "gpt-4.1",
    "o4-mini",
)
DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant in a terminal session."
DEFAULT_TIMEOUT = 120


class AIClientError(RuntimeError):
    """Raised when the AI backend cannot be configured or queried."""


@dataclass
class AIConfig:
    api_key: str
    model: str
    base_url: str
    system_prompt: str
    timeout: int = DEFAULT_TIMEOUT

    @property
    def chat_completions_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _parse_timeout(value: str | None) -> int:
    if value is None or not str(value).strip():
        return DEFAULT_TIMEOUT
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AIClientError("ADVAI_TIMEOUT must be an integer number of seconds") from exc
    if parsed <= 0:
        raise AIClientError("ADVAI_TIMEOUT must be greater than zero")
    return parsed


def load_ai_config(
    model: str | None = None,
    base_url: str | None = None,
    system_prompt: str | None = None,
    timeout: int | None = None,
) -> AIConfig:
    api_key = os.getenv("ADVAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise AIClientError("Set ADVAI_API_KEY or OPENAI_API_KEY before starting `advai tui`.")

    resolved_model = (
        model
        or os.getenv("ADVAI_MODEL")
        or os.getenv("OPENAI_MODEL")
        or DEFAULT_MODEL
    )
    resolved_base_url = (
        base_url
        or os.getenv("ADVAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    )
    resolved_system_prompt = system_prompt or os.getenv("ADVAI_SYSTEM_PROMPT") or DEFAULT_SYSTEM_PROMPT
    resolved_timeout = timeout if timeout is not None else _parse_timeout(os.getenv("ADVAI_TIMEOUT"))

    return AIConfig(
        api_key=api_key,
        model=resolved_model,
        base_url=resolved_base_url,
        system_prompt=resolved_system_prompt,
        timeout=resolved_timeout,
    )


def list_selectable_models(current_model: str | None = None) -> list[str]:
    raw_models = os.getenv("ADVAI_MODELS", "")
    configured_models = [item.strip() for item in raw_models.split(",") if item.strip()]
    base_models = configured_models or list(DEFAULT_TUI_MODELS)
    if current_model:
        return _dedupe_preserve_order([current_model, *base_models])
    return _dedupe_preserve_order(base_models)


def _build_messages(history: list[dict], system_prompt: str) -> list[dict]:
    messages = []
    prompt = str(system_prompt or "").strip()
    if prompt:
        messages.append({"role": "system", "content": prompt})
    for item in history:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role and content:
            messages.append({"role": role, "content": content})
    return messages


def _extract_text_content(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts).strip()
    return ""


def request_chat_completion(config: AIConfig, history: list[dict]) -> str:
    payload = {
        "model": config.model,
        "messages": _build_messages(history, config.system_prompt),
    }
    request = urllib.request.Request(
        config.chat_completions_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace").strip()
        message = error_body or exc.reason or "HTTP request failed"
        raise AIClientError(f"AI request failed: {message}") from exc
    except urllib.error.URLError as exc:
        raise AIClientError(f"Unable to reach AI backend: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AIClientError("AI backend returned invalid JSON") from exc

    choices = data.get("choices") or []
    if not choices:
        raise AIClientError("AI backend returned no choices")

    message = choices[0].get("message") or {}
    text = _extract_text_content(message.get("content"))
    if not text:
        raise AIClientError("AI backend returned an empty response")
    return text
