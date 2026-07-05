import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from advai.browser_bridge import (
    DEFAULT_BROWSER_CONTEXT_ID,
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_LOG_PATH,
    DEFAULT_DAEMON_PID_PATH,
    DEFAULT_DAEMON_PORT,
)


OPENCLI_DAEMON_HOST = "127.0.0.1"
OPENCLI_DAEMON_PORT = 19825
OPENCLI_BASE_URL = f"http://{OPENCLI_DAEMON_HOST}:{OPENCLI_DAEMON_PORT}"
OPENCLI_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-OpenCLI": "1",
}


class DaemonError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        hint: Optional[str] = None,
        status: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint
        self.status = status


class OpenCLIDaemonClient:
    def __init__(self, base_url: str = OPENCLI_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def ping(self) -> bool:
        try:
            request = urllib.request.Request(f"{self.base_url}/ping", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("ok") is True
        except Exception:
            return False

    def ensure_daemon(self, timeout: float = 15.0) -> None:
        if self.ping():
            return
        if shutil.which("opencli") is None:
            raise DaemonError(
                "Underlying browser engine is unavailable.",
                code="opencli_missing",
                hint="Install opencli and its browser extension, then rerun the browser command.",
                status=503,
            )
        try:
            subprocess.run(
                ["opencli", "daemon", "restart"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except Exception as exc:
            raise DaemonError(
                "Failed to start the underlying browser engine.",
                code="opencli_start_failed",
                hint="Run `opencli daemon restart` manually and verify the browser extension is connected.",
                status=503,
            ) from exc

        start = time.time()
        while time.time() - start < timeout:
            if self.ping():
                return
            time.sleep(0.25)

        raise DaemonError(
            "Underlying browser engine is not reachable.",
            code="opencli_unreachable",
            hint="Run `opencli daemon status` and make sure the browser extension is connected.",
            status=503,
        )

    def status(self, context_id: Optional[str] = None) -> dict[str, Any]:
        self.ensure_daemon()
        query = f"?contextId={urllib.parse.quote(context_id)}" if context_id else ""
        request = urllib.request.Request(
            f"{self.base_url}/status{query}",
            headers={"Accept": "application/json", "X-OpenCLI": "1"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def send_command(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_daemon()
        body = json.dumps({"action": action, **payload}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/command",
            data=body,
            headers=OPENCLI_HEADERS,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=payload.get("timeout", 65)) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_payload = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(error_payload)
            except json.JSONDecodeError:
                raise DaemonError(error_payload or "Browser command failed", status=exc.code) from exc
            raise DaemonError(
                parsed.get("error") or parsed.get("message") or "Browser command failed",
                code=parsed.get("errorCode"),
                hint=parsed.get("errorHint"),
                status=exc.code,
            ) from exc


class InternalBrowserBridge:
    def __init__(self, engine: Optional[OpenCLIDaemonClient] = None) -> None:
        self.engine = engine or OpenCLIDaemonClient()

    def list_extensions(self, context_id: Optional[str]) -> list[dict[str, Any]]:
        _ = context_id
        status = self.engine.status()
        profiles = status.get("profiles", [])
        return [
            {
                "contextId": profile.get("contextId"),
                "version": profile.get("extensionVersion") or "?",
            }
            for profile in profiles
        ]

    def handle_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        command_id = payload.get("id")
        if not command_id:
            raise DaemonError("Missing command id", status=400)
        action = payload.get("action")
        if not action:
            raise DaemonError("Missing action", status=400)

        if action in {
            "tabs",
            "navigate",
            "exec",
            "screenshot",
            "cdp",
            "network-capture-start",
            "network-capture-read",
            "wait-download",
            "frames",
        }:
            return self.engine.send_command(action, payload)

        if action == "close":
            return self.engine.send_command("close-window", payload)
        if action == "keys":
            return self.engine.send_command(
                "insert-text",
                {**payload, "text": payload.get("text", "")},
            )
        if action == "cookies":
            return self._cookies(payload)
        if action == "state":
            return self._state(payload)
        if action == "click":
            return self._selector_eval(payload, self._click_js(payload["selector"]))
        if action == "fill":
            return self._selector_eval(payload, self._fill_js(payload["selector"], payload.get("value", "")))
        if action == "select":
            return self._selector_eval(payload, self._select_js(payload["selector"], payload.get("option", "")))
        if action == "wait":
            return self._wait(payload)
        if action == "get":
            return self._get(payload)
        if action == "find":
            return self._find(payload)
        if action == "extract":
            return self._extract(payload)
        if action == "scroll":
            return self._scroll(payload)
        if action == "back":
            return self._back(payload)

        raise DaemonError(f"Unknown action: {action}", status=400)

    def _context_id(self, payload: dict[str, Any]) -> str:
        return str(payload.get("contextId") or DEFAULT_BROWSER_CONTEXT_ID)

    def _tabs(self, session: str, context_id: str) -> list[dict[str, Any]]:
        response = self.engine.send_command(
            "tabs",
            {
                "id": f"tabs_{int(time.time() * 1000)}",
                "session": session,
                "op": "list",
                "contextId": context_id,
                "timeout": 10,
            },
        )
        return response.get("data") or []

    def _resolve_page(self, payload: dict[str, Any]) -> str:
        if payload.get("page") is not None:
            return str(payload["page"])
        session = str(payload["session"])
        context_id = self._context_id(payload)
        tabs = self._tabs(session, context_id)
        for tab in tabs:
            if tab.get("active"):
                return str(tab["id"])
        if tabs:
            return str(tabs[-1]["id"])
        raise DaemonError(
            f'No active tab in session "{session}". Open a page first with `advai browser open {session} <url>`.',
            code="no_target",
            status=400,
        )

    def _exec(self, payload: dict[str, Any], code: str) -> dict[str, Any]:
        page = self._resolve_page(payload)
        return self.engine.send_command(
            "exec",
            {
                "id": f"exec_{int(time.time() * 1000)}",
                "session": payload["session"],
                "page": page,
                "contextId": self._context_id(payload),
                "code": code,
                "timeout": payload.get("timeout", 30),
            },
        )

    def _success(self, payload: dict[str, Any], data: Any, page: Optional[str] = None) -> dict[str, Any]:
        response = {
            "id": payload["id"],
            "ok": True,
            "data": data,
        }
        if page is not None:
            response["page"] = page
        return response

    def _selector_eval(self, payload: dict[str, Any], code: str) -> dict[str, Any]:
        result = self._exec(payload, code)
        return self._success(payload, result.get("data"), page=result.get("page"))

    def _state(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = str(payload["session"])
        context_id = self._context_id(payload)
        tabs = self._tabs(session, context_id)
        if payload.get("page") is not None:
            page = str(payload["page"])
        else:
            active = next((tab for tab in tabs if tab.get("active")), None)
            if active is None and tabs:
                active = tabs[-1]
            if active is None:
                raise DaemonError(
                    f'No active tab in session "{session}". Open a page first with `advai browser open {session} <url>`.',
                    code="no_target",
                    status=400,
                )
            page = str(active["id"])
        title_response = self.engine.send_command(
            "exec",
            {
                "id": f"exec_{int(time.time() * 1000)}",
                "session": session,
                "page": page,
                "contextId": context_id,
                "code": "document.title",
                "timeout": payload.get("timeout", 30),
            },
        )
        title = title_response.get("data")
        url = None
        for tab in tabs:
            if str(tab.get("id")) == page:
                url = tab.get("url")
                break
        if url is None:
            url = self.engine.send_command(
                "exec",
                {
                    "id": f"exec_{int(time.time() * 1000)}",
                    "session": session,
                    "page": page,
                    "contextId": context_id,
                    "code": "location.href",
                    "timeout": payload.get("timeout", 30),
                },
            ).get("data")
        data = {
            "page": page,
            "url": url,
            "title": title,
            "tabs": tabs,
        }
        return self._success(payload, data, page=page)

    def _cookies(self, payload: dict[str, Any]) -> dict[str, Any]:
        context_id = self._context_id(payload)
        forwarded = {
            "id": payload["id"],
            "session": payload["session"],
            "contextId": context_id,
            "timeout": payload.get("timeout", 30),
        }
        if payload.get("domain"):
            forwarded["domain"] = payload["domain"]
        else:
            session = str(payload["session"])
            tabs = self._tabs(session, context_id)
            if payload.get("page") is not None:
                page = str(payload["page"])
            else:
                active = next((tab for tab in tabs if tab.get("active")), None)
                if active is None and tabs:
                    active = tabs[-1]
                page = str(active["id"]) if active else ""
            current = next((tab for tab in tabs if str(tab.get("id")) == page), None)
            if current and current.get("url"):
                forwarded["url"] = current["url"]
        return self.engine.send_command("cookies", forwarded)

    def _wait(self, payload: dict[str, Any]) -> dict[str, Any]:
        selector = payload.get("selector")
        text = payload.get("text")
        timeout_raw = payload.get("timeout", 10000)
        timeout_ms = int(timeout_raw if timeout_raw > 1000 else timeout_raw * 1000)
        if not selector and not text:
            time.sleep(timeout_ms / 1000.0)
            return self._success(payload, {"waited": True, "timeoutMs": timeout_ms})

        if selector:
            probe = f"document.querySelector({json.dumps(selector)}) !== null"
        else:
            probe = f"document.body.innerText.includes({json.dumps(text)})"

        deadline = time.time() + (timeout_ms / 1000.0)
        while time.time() < deadline:
            result = self._exec(payload, probe).get("data")
            if result is True:
                return self._success(payload, {"waited": True, "timeoutMs": timeout_ms})
            time.sleep(0.2)
        raise DaemonError(
            "Wait condition timed out",
            code="timeout",
            status=408,
        )

    def _get(self, payload: dict[str, Any]) -> dict[str, Any]:
        selector = payload.get("selector")
        if not selector:
            return self._state(payload)
        code = f"""
(() => {{
  const nodes = Array.from(document.querySelectorAll({json.dumps(selector)}));
  if (!nodes.length) return null;
  const el = nodes[0];
  return {{
    matches: nodes.length,
    text: (el.innerText || el.textContent || '').trim(),
    value: ('value' in el) ? el.value : null,
    html: el.outerHTML,
    attributes: Object.fromEntries(Array.from(el.attributes || []).map(attr => [attr.name, attr.value])),
  }};
}})()
"""
        result = self._exec(payload, code)
        return self._success(payload, result.get("data"), page=result.get("page"))

    def _find(self, payload: dict[str, Any]) -> dict[str, Any]:
        selector = payload["selector"]
        code = f"""
(() => Array.from(document.querySelectorAll({json.dumps(selector)})).map((el, index) => ({{
  index,
  text: (el.innerText || el.textContent || '').trim(),
  tag: (el.tagName || '').toLowerCase(),
  html: el.outerHTML,
}})))()
"""
        result = self._exec(payload, code)
        entries = result.get("data") or []
        return self._success(
            payload,
            {"matches_n": len(entries), "entries": entries},
            page=result.get("page"),
        )

    def _extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        code = payload.get("code") or "document.body.innerText"
        result = self._exec(payload, code)
        return self._success(payload, result.get("data"), page=result.get("page"))

    def _scroll(self, payload: dict[str, Any]) -> dict[str, Any]:
        selector = payload.get("selector")
        if selector:
            code = f"""
(() => {{
  const el = document.querySelector({json.dumps(selector)});
  if (!el) return {{scrolled: false}};
  el.scrollIntoView({{behavior: 'instant', block: 'center', inline: 'nearest'}});
  return {{scrolled: true}};
}})()
"""
        else:
            code = "window.scrollBy(0, window.innerHeight); ({scrolled: true, direction: 'down'})"
        result = self._exec(payload, code)
        return self._success(payload, result.get("data"), page=result.get("page"))

    def _back(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._exec(payload, "history.back(); ({navigated: true})")
        return self._success(payload, result.get("data"), page=result.get("page"))

    def _click_js(self, selector: str) -> str:
        return f"""
(() => {{
  const nodes = Array.from(document.querySelectorAll({json.dumps(selector)}));
  if (!nodes.length) return {{clicked: false, matches_n: 0}};
  nodes[0].click();
  return {{clicked: true, matches_n: nodes.length}};
}})()
"""

    def _fill_js(self, selector: str, value: str) -> str:
        return f"""
(() => {{
  const nodes = Array.from(document.querySelectorAll({json.dumps(selector)}));
  if (!nodes.length) return {{filled: false, matches_n: 0}};
  const el = nodes[0];
  const nextValue = {json.dumps(value)};
  const dispatchBeforeInput = () => {{
    try {{
      el.dispatchEvent(new InputEvent('beforeinput', {{
        bubbles: true,
        cancelable: true,
        inputType: 'insertText',
        data: String(nextValue),
      }}));
    }} catch (_err) {{
      el.dispatchEvent(new Event('beforeinput', {{ bubbles: true, cancelable: true }}));
    }}
  }};
  if ('value' in el) {{
    el.focus();
    const proto =
      el instanceof HTMLInputElement ? HTMLInputElement.prototype :
      el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype :
      Object.getPrototypeOf(el);
    const valueDescriptor = proto ? Object.getOwnPropertyDescriptor(proto, 'value') : null;
    if (valueDescriptor && typeof valueDescriptor.set === 'function') {{
      valueDescriptor.set.call(el, nextValue);
    }} else {{
      el.value = nextValue;
    }}
    if (typeof el.setSelectionRange === 'function') {{
      const end = String(nextValue).length;
      el.setSelectionRange(end, end);
    }}
    dispatchBeforeInput();
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }} else if (el.isContentEditable) {{
    el.focus();
    el.textContent = nextValue;
    dispatchBeforeInput();
    el.dispatchEvent(new Event('input', {{ bubbles: true }}));
    el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }} else {{
    return {{filled: false, matches_n: nodes.length}};
  }}
  return {{filled: true, matches_n: nodes.length, value: ('value' in el) ? el.value : el.textContent}};
}})()
"""

    def _select_js(self, selector: str, option: str) -> str:
        return f"""
(() => {{
  const nodes = Array.from(document.querySelectorAll({json.dumps(selector)}));
  if (!nodes.length) return {{selected: false, matches_n: 0}};
  const el = nodes[0];
  if (!(el instanceof HTMLSelectElement)) return {{selected: false, matches_n: nodes.length}};
  const match = Array.from(el.options).find(opt => opt.value === {json.dumps(option)} || opt.text.trim() === {json.dumps(option)});
  if (!match) return {{selected: false, matches_n: nodes.length}};
  el.value = match.value;
  el.dispatchEvent(new Event('input', {{ bubbles: true }}));
  el.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return {{selected: true, matches_n: nodes.length, value: el.value}};
}})()
"""


BRIDGE = InternalBrowserBridge()


class AdvaiBrowserDaemonHandler(BaseHTTPRequestHandler):
    server_version = "advai-browser-daemon/1.0"

    def do_GET(self) -> None:
        if self.path == "/ping":
            self._json(200, {"ok": True})
            return
        if self.path == "/extensions":
            try:
                extensions = BRIDGE.list_extensions(context_id=DEFAULT_BROWSER_CONTEXT_ID)
                self._json(200, {"ok": True, "extensions": extensions})
            except DaemonError as exc:
                self._error(exc)
            return
        self._json(404, {"ok": False, "error": "Not found"})

    def do_POST(self) -> None:
        if self.path != "/command":
            self._json(404, {"ok": False, "error": "Not found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8") or "{}")
            response = BRIDGE.handle_command(payload)
            self._json(200, response)
        except DaemonError as exc:
            self._error(exc)
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "Invalid JSON"})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: DaemonError) -> None:
        payload = {"ok": False, "error": str(exc)}
        if exc.code:
            payload["errorCode"] = exc.code
        if exc.hint:
            payload["errorHint"] = exc.hint
        self._json(exc.status, payload)


def main() -> None:
    os.makedirs(os.path.dirname(DEFAULT_DAEMON_LOG_PATH), exist_ok=True)
    with open(DEFAULT_DAEMON_PID_PATH, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    server = ThreadingHTTPServer((DEFAULT_DAEMON_HOST, DEFAULT_DAEMON_PORT), AdvaiBrowserDaemonHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
