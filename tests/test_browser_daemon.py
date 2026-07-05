import asyncio
import socket
import unittest
from unittest import mock

import aiohttp

from advai.browser_daemon import DaemonError, EmbeddedExtensionDaemon, ExtensionDaemonClient, InternalBrowserBridge


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class EmbeddedExtensionDaemonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.port = _unused_port()
        self.daemon = EmbeddedExtensionDaemon(host="127.0.0.1", port=self.port)
        await self.daemon.start()

    async def asyncTearDown(self):
        await self.daemon.shutdown()

    async def test_extensions_endpoint_is_empty_without_connections(self):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"http://127.0.0.1:{self.port}/extensions") as response:
                payload = await response.json()

        self.assertEqual(payload["extensions"], [])

    async def test_command_roundtrip_with_mock_extension(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(f"http://127.0.0.1:{self.port}/ext") as ws:
                await ws.send_json(
                    {
                        "type": "hello",
                        "contextId": "ctx-demo",
                        "version": "1.0.0",
                        "compatRange": ">=1.0.0",
                    }
                )
                ack = await ws.receive_json()
                self.assertEqual(ack["type"], "hello-ack")

                async def issue_command():
                    async with session.post(
                        f"http://127.0.0.1:{self.port}/command",
                        json={"id": "cmd1", "action": "exec", "contextId": "ctx-demo", "code": "2+2"},
                    ) as command_response:
                        return await command_response.json()

                command_task = asyncio.create_task(issue_command())
                forwarded = await ws.receive_json()
                self.assertEqual(forwarded["id"], "cmd1")
                self.assertEqual(forwarded["action"], "exec")
                await ws.send_json({"id": "cmd1", "ok": True, "data": 4, "page": "9"})

                result = await command_task

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], 4)
        self.assertEqual(result["page"], "9")


class InternalBrowserBridgeTests(unittest.TestCase):
    def test_extension_client_ping_accepts_plaintext_pong(self):
        client = ExtensionDaemonClient()
        response = mock.Mock()
        response.read.return_value = b"pong"
        response.__enter__ = mock.Mock(return_value=response)
        response.__exit__ = mock.Mock(return_value=None)

        with mock.patch("urllib.request.urlopen", return_value=response):
            self.assertTrue(client.ping())

    def test_extension_client_reports_embedded_daemon_unreachable(self):
        client = ExtensionDaemonClient()

        with mock.patch.object(client, "ping", return_value=False), mock.patch("advai.browser_daemon.time.sleep"):
            with self.assertRaises(DaemonError) as ctx:
                client.ensure_daemon(timeout=0.1)

        self.assertEqual(ctx.exception.code, "embedded_extension_daemon_unreachable")
        self.assertIn("advai.browser_daemon", ctx.exception.hint)

    def test_list_extensions_delegates_to_embedded_daemon(self):
        engine = mock.Mock()
        engine.list_extensions.return_value = [
            {"contextId": "ctx-dev-v1000", "version": "1.0.0"},
        ]
        bridge = InternalBrowserBridge(engine=engine)

        result = bridge.list_extensions("ctx-dev-v1000")

        self.assertEqual(result[0]["contextId"], "ctx-dev-v1000")
        engine.list_extensions.assert_called_once_with("ctx-dev-v1000")

    def test_state_uses_active_tab_and_title(self):
        engine = mock.Mock()
        engine.send_command.side_effect = [
            {
                "ok": True,
                "data": [
                    {"id": 11, "url": "https://example.com", "title": "Example", "active": True},
                ],
            },
            {
                "ok": True,
                "data": "Example Title",
                "page": "11",
            },
        ]
        bridge = InternalBrowserBridge(engine=engine)

        response = bridge.handle_command(
            {
                "id": "cmd1",
                "action": "state",
                "session": "demo",
                "contextId": "ctx-demo",
            }
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["page"], "11")
        self.assertEqual(response["data"]["url"], "https://example.com")
        self.assertEqual(response["data"]["title"], "Example Title")

    def test_cookies_without_domain_use_current_tab_url(self):
        engine = mock.Mock()
        engine.send_command.side_effect = [
            {
                "ok": True,
                "data": [
                    {"id": 22, "url": "https://www.zhihu.com/hot", "title": "Zhihu", "active": True},
                ],
            },
            {
                "ok": True,
                "data": [
                    {"name": "SESSIONID", "value": "abc"},
                ],
            },
        ]
        bridge = InternalBrowserBridge(engine=engine)

        response = bridge.handle_command(
            {
                "id": "cmd2",
                "action": "cookies",
                "session": "zhihu",
                "contextId": "ctx-demo",
            }
        )

        self.assertTrue(response["ok"])
        engine.send_command.assert_any_call(
            "cookies",
            {
                "id": "cmd2",
                "session": "zhihu",
                "contextId": "ctx-demo",
                "timeout": 30,
                "url": "https://www.zhihu.com/hot",
            },
        )
        self.assertEqual(response["data"][0]["name"], "SESSIONID")

    def test_wait_selector_polls_until_match(self):
        engine = mock.Mock()
        bridge = InternalBrowserBridge(engine=engine)
        bridge._exec = mock.Mock(
            side_effect=[
                {"ok": True, "data": False, "page": "33"},
                {"ok": True, "data": True, "page": "33"},
            ]
        )

        response = bridge.handle_command(
            {
                "id": "cmd3",
                "action": "wait",
                "session": "demo",
                "contextId": "ctx-demo",
                "selector": "#app",
                "timeout": 1500,
            }
        )

        self.assertTrue(response["ok"])
        self.assertTrue(response["data"]["waited"])
        self.assertEqual(bridge._exec.call_count, 2)

    def test_fill_js_uses_native_value_setter_and_beforeinput(self):
        bridge = InternalBrowserBridge(engine=mock.Mock())

        script = bridge._fill_js("#name", "advai")

        self.assertIn("Object.getOwnPropertyDescriptor(proto, 'value')", script)
        self.assertIn("new InputEvent('beforeinput'", script)
        self.assertIn("valueDescriptor.set.call(el, nextValue)", script)
        self.assertIn("el.setSelectionRange(end, end)", script)


if __name__ == "__main__":
    unittest.main()
