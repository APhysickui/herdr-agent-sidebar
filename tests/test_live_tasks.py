"""Regression checks for stale names, cross-session matching and Kimi states."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from settings import Settings

from live_tasks import kimi_state, pi_session_title, reconcile
from sync import sidebar_values


class LiveTasksTest(unittest.TestCase):
    def test_session_match_uses_content_not_newest_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "--Users-example--"
            folder.mkdir()
            answers = ["唯一的工作内容第一行足够长并且表示正在进行的项目甲", "唯一的工作内容第二行足够长并且详细说明当前实现甲"]
            def write(name, question, answer):
                rows = [{"type": "session", "cwd": "/Users/example"},
                        {"type": "message", "message": {"role": "user", "content": question}},
                        {"type": "message", "message": {"role": "assistant", "content": answer}}]
                (folder / name).write_text("\n".join(json.dumps(r) for r in rows))
            write("old.jsonl", "实现 FlashAttention 并验证计算结果", "\n".join(answers))
            write("new.jsonl", "整理完全不同的历史资料", "其他会话的答复，与当前窗格的可见内容完全无关")
            self.assertEqual(pi_session_title({"cwd": "/Users/example"}, "\n".join(answers), root),
                             "实现 FlashAttention 并验证计算结果")
            self.assertIsNone(pi_session_title({"cwd": "/Users/example"}, "不够确定", root))

    def test_live_title_changes_and_manual_title_wins(self):
        pane = {"pane_id": "test:p1", "agent": "pi", "cwd": "/Users/example", "_live_task": "新的任务"}
        self.assertEqual(sidebar_values(pane)["task"], "新的任务")
        self.assertIsNone(sidebar_values(dict(pane, label="用户手动命名"))["task"])

    def test_kimi_static_thinking_footer_is_idle(self):
        footer = "\n │ >                       │\n Kimi-K3 thinking\n context: 32%"
        self.assertEqual(kimi_state(footer), "idle")
        self.assertEqual(kimi_state(" ⠋ Thinking…\n" + footer), "working")
        self.assertEqual(kimi_state("↵ confirm choose approve reject\n" + footer), "blocked")
        self.assertIsNone(kimi_state("a shell displaying old Kimi documentation"))

    def test_custom_identity_is_released_when_real_process_exits(self):
        pane = {"pane_id": "test:p1", "agent": "kimi-local"}
        info = json.dumps({"result": {"process_info": {"foreground_processes": [{"name": "zsh", "argv0": "zsh"}]}}})
        with patch("live_tasks.run", return_value=info) as run:
            reconcile("herdr", pane, periodic=True)
        self.assertNotIn("agent", pane)
        self.assertTrue(any("release-agent" in call.args for call in run.call_args_list))

    def test_acknowledged_but_ignored_report_does_not_fabricate_identity(self):
        pane = {"pane_id": "test:p1"}
        info = json.dumps({"result": {"process_info": {"foreground_processes": [{"name": "kimi", "argv0": "kimi-co"}]}}})
        screen = ' │ >                     │\n Kimi-K3 thinking\n context: 32%'
        response = json.dumps({"result": {"pane": {"pane_id": "test:p1"}}})
        with patch("live_tasks.run", side_effect=[info, screen, '{"result":{"type":"ok"}}', response]) as run:
            reconcile("herdr", pane, periodic=True, settings=Settings(kimi_compat=True))
        self.assertNotIn("agent", pane)
        self.assertFalse(any("report-metadata" in call.args for call in run.call_args_list))


if __name__ == "__main__":
    unittest.main()
