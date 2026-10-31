from types import SimpleNamespace
import unittest

from summaries import Summaries, compact_cells


class SummaryTests(unittest.TestCase):
    def settings(self):
        return SimpleNamespace(summary_provider="test", summary_model="test-model")

    def test_tab_width_counts_chinese_cells_instead_of_characters(self):
        self.assertEqual(compact_cells("这是一个很长的标签页名字", 14), "这是一个很长的")
        self.assertEqual(compact_cells("Herdr 命名", 14), "Herdr 命名")

    def test_uncached_request_never_exposes_raw_question_as_title(self):
        summaries = Summaries({}, self.settings(), backend=lambda jobs, settings: {})
        try:
            pane = {"pane_id": "test:p1", "agent": "codex", "cwd": str(__import__('pathlib').Path.home())}
            label = summaries.get(pane, "Please could you fix my very long task description")
            self.assertEqual(label["pane"], "Codex 任务")
        finally:
            summaries.pool.shutdown()

    def test_generation_is_cached_and_reuses_previous_summary_during_update(self):
        calls = []
        def backend(jobs, settings):
            calls.append(jobs)
            return {job['id']: {"pane": "Herdr 标题优化", "tab": "Herdr 命名"} for job in jobs}
        state = {}
        summaries = Summaries(state, self.settings(), backend=backend)
        pane = {"pane_id": "test:p1", "agent": "codex", "cwd": "/tmp/project"}
        try:
            summaries.get(pane, "Make the pane and tab names much shorter")
            summaries.flush()
            summaries.future.result(timeout=2)
            self.assertEqual(summaries.get(pane, "Make the pane and tab names much shorter")["tab"], "Herdr 命名")
            summaries.flush()
            self.assertEqual(len(calls), 1)
            updated = summaries.get(pane, "Also summarize the current task instead of clipping it")
            self.assertEqual(updated["tab"], "Herdr 命名")
            self.assertEqual(len(summaries.pending), 1)
            self.assertNotIn("Make the pane", str(state))
        finally:
            summaries.pool.shutdown()

    def test_generation_failure_backs_off_instead_of_repeating_every_refresh(self):
        def backend(jobs, settings):
            raise OSError("network unavailable")
        summaries = Summaries({}, self.settings(), backend=backend)
        pane = {"pane_id": "test:p1", "agent": "codex", "cwd": "/tmp/project"}
        try:
            summaries.get(pane, "Make the pane and tab names much shorter")
            summaries.flush()
            try:
                summaries.future.result(timeout=2)
            except OSError:
                pass
            summaries.get(pane, "Make the pane and tab names much shorter")
            self.assertFalse(summaries.pending)
            self.assertTrue(summaries.failed)
        finally:
            summaries.pool.shutdown()
