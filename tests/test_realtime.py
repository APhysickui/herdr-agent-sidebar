import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from realtime import API, Engine, SessionTitles, tab_name


class FakeAPI:
    def __init__(self):
        self.snapshot = {"panes": [{"pane_id": "test:p1", "tab_id": "test:t1", "agent": "pi",
                                   "cwd": "/tmp/project", "focused": True, "tokens": {}}],
                         "tabs": [{"tab_id": "test:t1", "label": "old tab"}]}
        self.writes = []

    def call(self, method, **params):
        if method == "session.snapshot":
            return {"snapshot": copy.deepcopy(self.snapshot)}
        self.writes.append((method, params))
        if method == "pane.report_metadata":
            self.snapshot["panes"][0]["tokens"].update(params["tokens"])
        elif method == "tab.rename":
            self.snapshot["tabs"][0]["label"] = params["label"]
        return {}


class Titles:
    title = "Search API"

    def resolve(self, pane, api):
        return self.title


class RealtimeTests(unittest.TestCase):
    def test_subscription_uses_valid_wildcards_and_checks_server_response(self):
        client = Mock()
        client.recv.return_value = b'{"result":{"type":"events_subscribed"}}\n'
        with patch('realtime.socket.socket', return_value=client):
            self.assertIs(API('/test.sock').subscribe(), client)
        payload = json.loads(client.sendall.call_args.args[0])
        names = [event['type'] for event in payload['params']['subscriptions']]
        # These events require an explicit pane_id; omitting it rejects the whole request.
        self.assertNotIn('pane.agent_status_changed', names)
        self.assertIn('pane.updated', names)
        client.recv.return_value = b'{"error":{"message":"invalid subscription"}}\n'
        with patch('realtime.socket.socket', return_value=client), self.assertRaises(ValueError):
            API('/test.sock').subscribe()
        self.assertTrue(client.close.called)

    def test_new_prompt_updates_pane_and_tab_in_same_pass(self):
        api, titles, state = FakeAPI(), Titles(), {}
        engine = Engine(api, state, titles, auto_tabs=True, adopt_tabs=True)
        self.assertEqual(engine.refresh(), 2)
        self.assertEqual(api.snapshot["tabs"][0]["label"], "Search API")
        titles.title = "Review citations"
        self.assertEqual(engine.refresh(), 2)
        self.assertEqual(api.snapshot["panes"][0]["tokens"]["task"], "Review citations")
        self.assertEqual(api.snapshot["tabs"][0]["label"], "Review citations")

    def test_self_generated_events_do_not_cause_more_writes(self):
        api = FakeAPI()
        engine = Engine(api, {}, Titles(), auto_tabs=True, adopt_tabs=True)
        engine.refresh()
        before = len(api.writes)
        self.assertEqual(engine.refresh(), 0)
        self.assertEqual(len(api.writes), before)

    def test_user_tab_rename_is_preserved_after_adoption(self):
        api, state = FakeAPI(), {}
        engine = Engine(api, state, Titles(), auto_tabs=True, adopt_tabs=True)
        engine.refresh()
        api.snapshot["tabs"][0]["label"] = "My pinned tab"
        engine.refresh()
        self.assertEqual(api.snapshot["tabs"][0]["label"], "My pinned tab")
        self.assertTrue(state["tabs"]["test:t1"]["manual"])

    def test_split_tab_keeps_only_primary_project_without_counts(self):
        tab = {"tab_id": "test:t1"}
        panes = [{"pane_id": "test:p1", "tab_id": "test:t1", "agent": "codex", "tokens": {"task": "Write tests"}},
                 {"pane_id": "test:p2", "tab_id": "test:t1", "agent": "pi", "focused": True, "tokens": {"task": "Review code"}}]
        self.assertEqual(tab_name(tab, panes), "Review code")

    def test_descriptive_labels_keep_project_and_action(self):
        tab = {"tab_id": "test:t1"}
        panes = [{"pane_id": "test:p1", "tab_id": "test:t1", "agent": "codex",
                  "_tab_task": "Herdr 侧栏", "tokens": {"task": "Herdr 侧栏命名优化"}},
                 {"pane_id": "test:p2", "tab_id": "test:t1", "tokens": {"task": "声子热霍尔"}}]
        label = tab_name(tab, panes)
        self.assertEqual(label, "Herdr 侧栏")
        self.assertNotIn('+1', label)

    def test_codex_new_and_old_log_formats_and_file_updates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rollout.jsonl"
            path.write_text(json.dumps({"type": "event_msg", "payload": {"type": "user_message", "message": "Implement a search endpoint"}}) + "\n")
            titles = SessionTitles()
            self.assertEqual(titles.latest_codex(path), "Implement a search endpoint")
            with path.open("a") as file:
                file.write(json.dumps({"type": "response_item", "payload": {"role": "user", "content": [{"type": "input_text", "text": "Review the documentation instead"}]}}) + "\n")
                file.write(json.dumps({"type": "response_item", "payload": {"role": "user", "content": [{"type": "input_text", "text": "<environment_context>internal setup</environment_context>"}]}}) + "\n")
            self.assertEqual(titles.latest_codex(path), "Review the documentation instead")

    def test_kimi_uses_current_prompt_instead_of_original_session_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = home / ".kimi-code/sessions/project/session-test/state.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"title": "Old subject", "lastPrompt": "Check the current paper references"}))
            title = SessionTitles(home).kimi_title({"agent_session": {"value": "session-test"}})
            self.assertEqual(title, "Check the current paper references")
