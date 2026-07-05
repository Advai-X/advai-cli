import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Optional


DEFAULT_DAEMON_HOST = "127.0.0.1"
DEFAULT_DAEMON_PORT = 19825
DEFAULT_BROWSER_STATE_DIR = os.path.expanduser("~/.advai/browser")
DEFAULT_DAEMON_LOG_PATH = os.path.join(DEFAULT_BROWSER_STATE_DIR, "daemon.log")
DEFAULT_DAEMON_PID_PATH = os.path.join(DEFAULT_BROWSER_STATE_DIR, "daemon.pid")
DEFAULT_BROWSER_CONTEXT_ID = "ctx-dev-v1000"
DEFAULT_EXTENSION_WAIT_TIMEOUT = 35.0


class BrowserBridgeError(Exception):
    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


def load_browser_context_id(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit
    return DEFAULT_BROWSER_CONTEXT_ID


def new_browser_command_id() -> str:
    return uuid.uuid4().hex[:16]


class BrowserBridgeClient:
    def __init__(
        self,
        host: str = DEFAULT_DAEMON_HOST,
        port: int = DEFAULT_DAEMON_PORT,
        context_id: Optional[str] = DEFAULT_BROWSER_CONTEXT_ID,
        default_timeout: int = 60,
    ) -> None:
        self.host = host
        self.port = port
        self.context_id = context_id
        self.default_timeout = default_timeout

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def daemon_log_path(self) -> str:
        return DEFAULT_DAEMON_LOG_PATH

    @property
    def daemon_pid_path(self) -> str:
        return DEFAULT_DAEMON_PID_PATH

    def ping_daemon(self) -> bool:
        try:
            body = self._request_bytes("GET", "/ping", timeout=2)
        except BrowserBridgeError:
            return False
        if body.decode("utf-8", errors="replace").strip() == "pong":
            return True
        try:
            response = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return False
        return response.get("ok") is True

    def list_extensions(self) -> list[dict[str, Any]]:
        self.ensure_daemon()
        response = self._request_json("GET", "/extensions", timeout=5)
        return response.get("extensions", [])

    def ensure_daemon(self, timeout: int = 30) -> None:
        if self.ping_daemon():
            return

        if self.can_start_daemon():
            self._start_daemon_background()
        else:
            raise BrowserBridgeError(
                "Browser bridge daemon is not running.",
                code="daemon_unavailable",
                hint=(
                    "Install advai-x-crx in the same Python environment, or start it "
                    "manually with `python -m advai_crx.daemon`, then load the Chrome extension."
                ),
            )

        start = time.time()
        while time.time() - start < timeout:
            if self.ping_daemon():
                return
            time.sleep(0.5)

        raise BrowserBridgeError(
            "Browser bridge daemon failed to start.",
            code="daemon_start_failed",
            hint=f"Check the daemon log at {self.daemon_log_path}",
        )

    def can_start_daemon(self) -> bool:
        try:
            return importlib.util.find_spec("advai_crx.daemon") is not None
        except ModuleNotFoundError:
            return False

    def send_command(
        self,
        action: str,
        *,
        timeout: Optional[float] = None,
        **payload: Any,
    ) -> dict[str, Any]:
        self.ensure_daemon()
        self.wait_for_extension(timeout=DEFAULT_EXTENSION_WAIT_TIMEOUT)

        command: dict[str, Any] = {
            "id": payload.pop("id", new_browser_command_id()),
            "action": action,
        }
        for key, value in payload.items():
            if value is not None:
                command[key] = value
        if self.context_id:
            command["contextId"] = self.context_id
        if "timeout" not in command:
            command["timeout"] = timeout if timeout is not None else self.default_timeout

        response = self._request_json(
            "POST",
            "/command",
            payload=command,
            timeout=self._http_timeout_for_command(command["timeout"]),
        )
        if not response.get("ok"):
            raise BrowserBridgeError(
                response.get("error") or "Unknown browser bridge error",
                code=response.get("errorCode"),
                hint=response.get("errorHint"),
            )
        return response

    def wait_for_extension(self, timeout: float = DEFAULT_EXTENSION_WAIT_TIMEOUT) -> None:
        start = time.time()
        last_extensions: list[dict[str, Any]] = []
        while time.time() - start < timeout:
            response = self._request_json("GET", "/extensions", timeout=5)
            extensions = response.get("extensions", [])
            last_extensions = extensions
            if self.context_id:
                if any(ext.get("contextId") == self.context_id for ext in extensions):
                    return
            elif extensions:
                return
            time.sleep(0.5)

        if self.context_id:
            known = ", ".join(ext.get("contextId", "?") for ext in last_extensions) or "none"
            raise BrowserBridgeError(
                f"Extension context not connected yet: {self.context_id}",
                code="extension_not_ready",
                hint=(
                    f"Wait for the Chrome extension to reconnect. Connected contexts: {known}. "
                    "Refreshing the extension popup can force a reconnect."
                ),
            )
        raise BrowserBridgeError(
            "No Chrome extension connected.",
            code="extension_not_ready",
            hint="Wait for the extension to reconnect or refresh it in chrome://extensions.",
        )

    def _start_daemon_background(self) -> None:
        if self.ping_daemon():
            return
        os.makedirs(os.path.dirname(self.daemon_log_path), exist_ok=True)
        with open(self.daemon_log_path, "a", encoding="utf-8") as log_handle:
            subprocess.Popen(
                [sys.executable, "-m", "advai_crx.daemon"],
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )
        time.sleep(0.5)

    def _http_timeout_for_command(self, command_timeout: Any) -> float:
        if isinstance(command_timeout, (int, float)):
            if command_timeout > 1000:
                return max(10.0, (float(command_timeout) / 1000.0) + 5.0)
            return max(10.0, float(command_timeout) + 5.0)
        return 65.0

    def _request_json(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        raw = self._request_bytes(method, path, payload=payload, timeout=timeout)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise BrowserBridgeError("Browser bridge returned invalid JSON") from exc

    def _request_bytes(
        self,
        method: str,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        timeout: float = 10.0,
    ) -> bytes:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            message = self._parse_error_body(exc.read())
            raise BrowserBridgeError(message, code="http_error") from exc
        except urllib.error.URLError as exc:
            raise BrowserBridgeError(
                f"Cannot reach browser bridge daemon at {self.base_url}",
                code="daemon_unreachable",
                hint=(
                    "Start advai-x-crx with `python -m advai_crx.daemon` and make sure "
                    "the Chrome extension is installed."
                ),
            ) from exc

    def _parse_error_body(self, body: bytes) -> str:
        if not body:
            return "Browser bridge request failed"
        try:
            payload = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return body.decode("utf-8", errors="replace").strip() or "Browser bridge request failed"
        return payload.get("error") or payload.get("message") or "Browser bridge request failed"
