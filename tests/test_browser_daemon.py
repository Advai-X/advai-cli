import unittest
from unittest import mock

from advai.browser_daemon import InternalBrowserBridge


class InternalBrowserBridgeTests(unittest.TestCase):
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
