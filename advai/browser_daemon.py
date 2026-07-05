import asyncio
import dataclasses
import errno
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Optional

from aiohttp import WSMsgType, web

from advai.browser_bridge import (
    DEFAULT_BROWSER_CONTEXT_ID,
    DEFAULT_DAEMON_HOST,
    DEFAULT_DAEMON_LOG_PATH,
    DEFAULT_DAEMON_PID_PATH,
    DEFAULT_DAEMON_PORT,
)


EXTENSION_DAEMON_HOST = "127.0.0.1"
EXTENSION_DAEMON_PORT = 19827
EXTENSION_DAEMON_BASE_URL = f"http://{EXTENSION_DAEMON_HOST}:{EXTENSION_DAEMON_PORT}"
EXTENSION_DAEMON_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
}

logger = logging.getLogger(__name__)


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


@dataclasses.dataclass
class ExtensionInfo:
    context_id: str
    version: str
    compat_range: str
    connected_at: float = dataclasses.field(default_factory=time.time)


class EmbeddedExtensionDaemon:
    def __init__(self, host: str = EXTENSION_DAEMON_HOST, port: int = EXTENSION_DAEMON_PORT) -> None:
        self.host = host
        self.port = port
        self.bound_port = port
        self._extensions: dict[str, tuple[web.WebSocketResponse, ExtensionInfo]] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._startup_error: Optional[BaseException] = None

    def _make_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/ping", self._handle_ping)
        app.router.add_get("/ext", self._handle_ws)
        app.router.add_post("/command", self._handle_command)
        app.router.add_get("/extensions", self._handle_list_extensions)
        return app

    async def start(self) -> None:
        if self._runner is not None:
            return
        self._app = self._make_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        if self._site._server and self._site._server.sockets:
            socket_name = self._site._server.sockets[0].getsockname()
            self.bound_port = int(socket_name[1])
        logger.info("Embedded extension daemon listening on %s:%d", self.host, self.bound_port)

    async def shutdown(self) -> None:
        await self._close_extensions()
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(ConnectionError("Extension daemon shutting down"))
        self._pending.clear()
        if self._runner is not None:
            await self._runner.cleanup()
        self._app = None
        self._runner = None
        self._site = None

    def start_background(self, timeout: float = 5.0) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._thread_main, name="advai-extension-daemon", daemon=True)
        self._thread.start()
        if not self._ready_event.wait(timeout):
            raise RuntimeError("Embedded extension daemon did not start in time")
        if self._startup_error is not None:
            if isinstance(self._startup_error, OSError) and self._startup_error.errno == errno.EADDRINUSE:
                raise RuntimeError(
                    f"Advai embedded extension daemon port {self.port} is already in use."
                ) from self._startup_error
            raise RuntimeError("Failed to start embedded extension daemon") from self._startup_error

    def stop_background(self, timeout: float = 5.0) -> None:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None:
            return
        future = asyncio.run_coroutine_threadsafe(self.shutdown(), loop)
        future.result(timeout=timeout)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout)
        self._loop = None
        self._thread = None

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.start())
        except BaseException as exc:
            self._startup_error = exc
            self._ready_event.set()
            loop.close()
            return
        self._ready_event.set()
        try:
            loop.run_forever()
        finally:
            if self._runner is not None:
                loop.run_until_complete(self.shutdown())
            loop.close()

    def list_extensions(self) -> list[dict[str, Any]]:
        return [
            {
                "contextId": context_id,
                "version": info.version,
                "compatRange": info.compat_range,
                "connectedAt": info.connected_at,
            }
            for context_id, (_ws, info) in self._extensions.items()
        ]

    async def send_command(self, body: dict[str, Any]) -> dict[str, Any]:
        cmd_id = body.get("id")
        if not cmd_id:
            raise DaemonError("Missing command id", status=400)

        context_id = body.get("contextId")
        if context_id and context_id not in self._extensions:
            raise DaemonError(
                f"Extension context not found: {context_id}",
                code="extension_not_found",
                status=404,
            )

        if not context_id:
            if not self._extensions:
                raise DaemonError(
                    "No Chrome extension connected.",
                    code="extension_not_ready",
                    hint="Open the browser extension popup or wait for it to reconnect.",
                    status=503,
                )
            context_id = next(iter(self._extensions.keys()))

        ws, _info = self._extensions[context_id]
        if ws.closed:
            del self._extensions[context_id]
            raise DaemonError("Extension connection closed", code="extension_closed", status=502)

        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[cmd_id] = future

        try:
            body["contextId"] = context_id
            await ws.send_json(body)
        except Exception as exc:
            self._pending.pop(cmd_id, None)
            raise DaemonError(f"Failed to send to extension: {exc}", code="extension_send_failed", status=502) from exc

        timeout = body.get("timeout", 60)
        if isinstance(timeout, (int, float)) and timeout > 1000:
            timeout = float(timeout) / 1000.0
        try:
            return await asyncio.wait_for(future, timeout=float(timeout))
        except asyncio.TimeoutError as exc:
            self._pending.pop(cmd_id, None)
            raise DaemonError("Command timed out", code="timeout", status=504) from exc

    async def _handle_ping(self, request: web.Request) -> web.Response:
        _ = request
        return web.Response(text="pong", content_type="text/plain")

    async def _handle_list_extensions(self, request: web.Request) -> web.Response:
        _ = request
        return web.json_response({"extensions": self.list_extensions()})

    async def _handle_command(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)
        try:
            response = await self.send_command(body)
            return web.json_response(response)
        except DaemonError as exc:
            payload = {"ok": False, "error": str(exc)}
            if exc.code:
                payload["errorCode"] = exc.code
            if exc.hint:
                payload["errorHint"] = exc.hint
            return web.json_response(payload, status=exc.status)

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        context_id: Optional[str] = None
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    data = json.loads(msg.data)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type == "hello":
                    context_id = data.get("contextId", "unknown")
                    info = ExtensionInfo(
                        context_id=context_id,
                        version=data.get("version", "unknown"),
                        compat_range=data.get("compatRange", ">=1.0.0"),
                    )
                    self._extensions[context_id] = (ws, info)
                    logger.info("Extension connected: context=%s version=%s", context_id, info.version)
                    await ws.send_json({"type": "hello-ack", "ok": True})
                    continue

                if msg_type == "log":
                    level = data.get("level", "info")
                    msg_text = data.get("msg", "")
                    log_method = getattr(logger, level, logger.info)
                    log_method("[ext] %s", msg_text)
                    continue

                if "id" in data and "ok" in data:
                    future = self._pending.pop(data["id"], None)
                    if future is not None and not future.done():
                        future.set_result(data)
        finally:
            if context_id and context_id in self._extensions:
                del self._extensions[context_id]
                logger.info("Extension disconnected: context=%s", context_id)
            for future in list(self._pending.values()):
                if not future.done():
                    future.set_exception(ConnectionError("Extension disconnected"))
            self._pending.clear()
        return ws

    async def _close_extensions(self) -> None:
        for context_id, (ws, _info) in list(self._extensions.items()):
            try:
                await ws.close(code=1001, message=b"daemon shutting down")
            except Exception as exc:
                logger.debug("Failed to close extension %s cleanly: %s", context_id, exc)
            finally:
                self._extensions.pop(context_id, None)


class ExtensionDaemonClient:
    def __init__(self, base_url: str = EXTENSION_DAEMON_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")

    def ping(self) -> bool:
        try:
            request = urllib.request.Request(f"{self.base_url}/ping", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                body = response.read()
            if body.decode("utf-8", errors="replace").strip() == "pong":
                return True
            payload = json.loads(body.decode("utf-8"))
            return payload.get("ok") is True
        except Exception:
            return False

    def ensure_daemon(self, timeout: float = 15.0) -> None:
        start = time.time()
        while time.time() - start < timeout:
            if self.ping():
                return
            time.sleep(0.25)

        raise DaemonError(
            "Embedded extension daemon is not reachable.",
            code="embedded_extension_daemon_unreachable",
            hint=(
                f"Restart `python -m advai.browser_daemon` and make sure the browser extension "
                f"is reloaded so it connects to Advai's dedicated extension port {EXTENSION_DAEMON_PORT}."
            ),
            status=503,
        )

    def list_extensions(self, context_id: Optional[str] = None) -> list[dict[str, Any]]:
        self.ensure_daemon()
        _ = context_id
        response = self._request_json("GET", "/extensions", timeout=5)
        return response.get("extensions", [])

    def send_command(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.ensure_daemon()
        body = json.dumps({"action": action, **payload}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/command",
            data=body,
            headers=EXTENSION_DAEMON_HEADERS,
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

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            headers={"Accept": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                raise DaemonError(payload or "Browser daemon request failed", status=exc.code) from exc
            raise DaemonError(
                parsed.get("error") or parsed.get("message") or "Browser daemon request failed",
                code=parsed.get("errorCode"),
                hint=parsed.get("errorHint"),
                status=exc.code,
            ) from exc


class InternalBrowserBridge:
    def __init__(self, engine: Optional[ExtensionDaemonClient] = None) -> None:
        self.engine = engine or ExtensionDaemonClient()

    def list_extensions(self, context_id: Optional[str]) -> list[dict[str, Any]]:
        return self.engine.list_extensions(context_id)

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

EMBEDDED_EXTENSION_DAEMON = EmbeddedExtensionDaemon()
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    os.makedirs(os.path.dirname(DEFAULT_DAEMON_LOG_PATH), exist_ok=True)
    pid_written = False
    try:
        with open(DEFAULT_DAEMON_PID_PATH, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
        pid_written = True
    except OSError as exc:
        logger.warning("Failed to write daemon pid file %s: %s", DEFAULT_DAEMON_PID_PATH, exc)
    try:
        EMBEDDED_EXTENSION_DAEMON.start_background()
    except RuntimeError as exc:
        logger.error("%s", exc)
        raise
    server = ThreadingHTTPServer((DEFAULT_DAEMON_HOST, DEFAULT_DAEMON_PORT), AdvaiBrowserDaemonHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        EMBEDDED_EXTENSION_DAEMON.stop_background()
        if pid_written:
            try:
                os.unlink(DEFAULT_DAEMON_PID_PATH)
            except OSError:
                pass


if __name__ == "__main__":
    main()
