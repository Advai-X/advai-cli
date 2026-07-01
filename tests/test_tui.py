import unittest

from advai.tui import _classify_picker_sequence, parse_tui_command


class TUICommandTests(unittest.TestCase):
    def test_parse_regular_text(self):
        self.assertEqual(parse_tui_command("hello"), ("", ""))

    def test_parse_command_without_argument(self):
        self.assertEqual(parse_tui_command("/help"), ("help", ""))

    def test_parse_model_command_without_argument(self):
        self.assertEqual(parse_tui_command("/model"), ("model", ""))

    def test_parse_agent_command_without_argument(self):
        self.assertEqual(parse_tui_command("/agent"), ("agent", ""))

    def test_parse_command_with_argument(self):
        self.assertEqual(
            parse_tui_command("/model gpt-4o-mini"),
            ("model", "gpt-4o-mini"),
        )

    def test_parse_agent_command_with_argument(self):
        self.assertEqual(parse_tui_command("/agent default"), ("agent", "default"))

    def test_classify_picker_sequence_for_arrow_keys(self):
        self.assertEqual(_classify_picker_sequence(b"\x1b[A"), "up")
        self.assertEqual(_classify_picker_sequence(b"\x1b[B"), "down")
        self.assertEqual(_classify_picker_sequence(b"\x1b[C"), "right")
        self.assertEqual(_classify_picker_sequence(b"\x1b[D"), "left")
        self.assertEqual(_classify_picker_sequence(b"\x1bOA"), "up")
        self.assertEqual(_classify_picker_sequence(b"\x1bOB"), "down")
        self.assertEqual(_classify_picker_sequence(b"\x7f"), "backspace")


if __name__ == "__main__":
    unittest.main()
