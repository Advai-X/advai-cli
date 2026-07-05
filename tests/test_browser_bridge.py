import base64
import os
import tempfile
import unittest
from unittest import mock

from click.testing import CliRunner

from advai.browser_bridge import (
    BrowserBridgeClient,
    BrowserBridgeError,
    DEFAULT_BROWSER_CONTEXT_ID,
)
from advai.cli import cli


class BrowserCliTests(unittest.TestCase):
    def _make_client(self):
        client = mock.Mock()
        client.host = "127.0.0.1"
        client.port = 19825
        client.context_id = None
        client.daemon_log_path = "/tmp/advai-crx.log"
        client.daemon_pid_path = "/tmp/advai-crx.pid"
        return client

    def test_browser_doctor_lists_connected_extensions(self):
        runner = CliRunner()
        client = self._make_client()
        client.ping_daemon.return_value = True
        client.list_extensions.return_value = [
            {"contextId": "ctx-demo", "version": "1.0.0"},
        ]

        with mock.patch("advai.cli.BrowserBridgeClient", return_value=client):
            result = runner.invoke(cli, ["browser", "doctor"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("daemon_running: yes", result.output)
        self.assertIn("connected_extensions: 1", result.output)
        self.assertIn("ctx-demo", result.output)

    def test_browser_uses_fixed_context_id(self):
        runner = CliRunner()
        client = self._make_client()
        client.context_id = DEFAULT_BROWSER_CONTEXT_ID
        client.ping_daemon.return_value = True
        client.list_extensions.return_value = []

        with mock.patch("advai.cli.BrowserBridgeClient", return_value=client) as client_cls:
            result = runner.invoke(cli, ["browser", "doctor"])

        self.assertEqual(result.exit_code, 0)
        client_cls.assert_called_once_with(
            host="127.0.0.1",
            port=19825,
            context_id=DEFAULT_BROWSER_CONTEXT_ID,
        )
        self.assertIn(f"context_id: {DEFAULT_BROWSER_CONTEXT_ID}", result.output)

    def test_browser_open_uses_tabs_new_command(self):
        runner = CliRunner()
        client = self._make_client()
        client.send_command.return_value = {"ok": True, "data": {"page": "12"}}

        with mock.patch("advai.cli.BrowserBridgeClient", return_value=client):
            result = runner.invoke(
                cli,
                ["browser", "open", "demo", "https://example.com"],
            )

        self.assertEqual(result.exit_code, 0)
        client.send_command.assert_called_once_with(
            "tabs",
            session="demo",
            op="new",
            url="https://example.com",
            windowMode=None,
        )
        self.assertIn('"page": "12"', result.output)

    def test_browser_exec_reads_code_from_stdin(self):
        runner = CliRunner()
        client = self._make_client()
        client.send_command.return_value = {"ok": True, "data": {"value": "Example"}}

        with mock.patch("advai.cli.BrowserBridgeClient", return_value=client):
            result = runner.invoke(
                cli,
                ["browser", "exec", "demo", "-"],
                input="document.title",
            )

        self.assertEqual(result.exit_code, 0)
        client.send_command.assert_called_once_with(
            "exec",
            session="demo",
            code="document.title",
            page=None,
        )

    def test_browser_wait_passes_selector_timeout(self):
        runner = CliRunner()
        client = self._make_client()
        client.send_command.return_value = {"ok": True, "data": {"waited": True}}

        with mock.patch("advai.cli.BrowserBridgeClient", return_value=client):
            result = runner.invoke(
                cli,
                ["browser", "wait", "demo", "--selector", "#app", "--timeout", "12000"],
            )

        self.assertEqual(result.exit_code, 0)
        client.send_command.assert_called_once_with(
            "wait",
            session="demo",
            selector="#app",
            text=None,
            page=None,
            waitFor="selector",
            timeout=12000,
        )

    def test_browser_screenshot_writes_output_file(self):
        runner = CliRunner()
        client = self._make_client()
        client.send_command.return_value = {
            "ok": True,
            "data": base64.b64encode(b"image-bytes").decode("ascii"),
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = os.path.join(temp_dir, "page.png")
            with mock.patch("advai.cli.BrowserBridgeClient", return_value=client):
                result = runner.invoke(
                    cli,
                    ["browser", "screenshot", "demo", "--output", output_path],
                )

            self.assertEqual(result.exit_code, 0)
            self.assertIn(f"Saved to {output_path}", result.output)
            with open(output_path, "rb") as handle:
                self.assertEqual(handle.read(), b"image-bytes")

    def test_browser_extensions_surfaces_bridge_hint(self):
        runner = CliRunner()
        client = self._make_client()
        client.list_extensions.side_effect = BrowserBridgeError(
            "Browser bridge daemon is not running.",
            hint="Start advai-x-crx first.",
        )

        with mock.patch("advai.cli.BrowserBridgeClient", return_value=client):
            result = runner.invoke(cli, ["browser", "extensions"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Browser bridge daemon is not running.", result.output)
        self.assertIn("Hint: Start advai-x-crx first.", result.output)


class BrowserBridgeClientTests(unittest.TestCase):
    def test_ping_daemon_accepts_plaintext_pong(self):
        client = BrowserBridgeClient()

        with mock.patch.object(client, "_request_bytes", return_value=b"pong"):
            self.assertTrue(client.ping_daemon())

    def test_send_command_waits_for_selected_extension(self):
        client = BrowserBridgeClient(context_id=DEFAULT_BROWSER_CONTEXT_ID)

        extension_responses = [
            {"extensions": []},
            {"extensions": [{"contextId": DEFAULT_BROWSER_CONTEXT_ID}]},
        ]

        def fake_request(method, path, payload=None, timeout=10.0):
            _ = payload, timeout
            if path == "/extensions":
                return extension_responses.pop(0)
            if path == "/command":
                return {"ok": True, "data": {"page": "demo"}}
            raise AssertionError(f"Unexpected path: {path}")

        with mock.patch.object(client, "ensure_daemon"), mock.patch.object(
            client, "_request_json", side_effect=fake_request
        ), mock.patch("advai.browser_bridge.time.sleep"):
            response = client.send_command("state", session="demo")

        self.assertEqual(response["data"]["page"], "demo")

    def test_can_start_daemon_returns_false_when_advai_crx_is_missing(self):
        client = BrowserBridgeClient()

        with mock.patch(
            "advai.browser_bridge.importlib.util.find_spec",
            side_effect=ModuleNotFoundError("No module named 'advai_crx'"),
        ):
            self.assertFalse(client.can_start_daemon())


if __name__ == "__main__":
    unittest.main()
