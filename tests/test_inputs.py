import json
from pathlib import Path
import tempfile
import unittest

from agent_input import request_for
from realtime import SessionTitles
from install import claude_config


class InputTests(unittest.TestCase):
    def test_claude_prompt_hook_never_writes_raw_task_as_a_title(self):
        request = request_for({'prompt': 'Please review my report', 'session_id': 'session-a',
                               'transcript_path': '/tmp/session-a.jsonl'}, 'test:p1')
        tokens = request['params']['tokens']
        self.assertEqual(tokens['live_task'], 'Please review my report')
        self.assertEqual(tokens['task_session'], 'session-a')
        self.assertNotIn('task', tokens)
        self.assertNotIn('title', request['params'])
        self.assertGreater(request['params']['seq'], 0)

    def test_claude_same_directory_instances_use_exact_pid_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / '.claude/sessions'
            project = home / '.claude/projects/project'
            sessions.mkdir(parents=True)
            project.mkdir(parents=True)
            for pid, sid, question in [(111, 'session-a', 'Review the paper references'),
                                       (222, 'session-b', 'Implement the search endpoint')]:
                (sessions / f'{pid}.json').write_text(json.dumps({'sessionId': sid, 'cwd': '/work'}))
                (project / f'{sid}.jsonl').write_text(json.dumps({'type': 'user', 'message': {'content': question}}) + '\n')
            class API:
                def call(self, method, **params):
                    pid = 111 if params['pane_id'] == 'test:p1' else 222
                    return {'process_info': {'foreground_processes': [{'pid': pid, 'name': 'claude.exe'}]}}
            titles = SessionTitles(home)
            self.assertEqual(titles.claude_title({'pane_id': 'test:p1', 'cwd': '/work'}, API()), 'Review the paper references')
            self.assertEqual(titles.claude_title({'pane_id': 'test:p2', 'cwd': '/work'}, API()), 'Implement the search endpoint')

    def test_claude_skips_model_commands_and_greetings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.jsonl'
            rows = [{'type': 'user', 'message': {'content': 'Review my manuscript references'}},
                    {'type': 'user', 'message': {'content': '<command-name>/model</command-name>'}},
                    {'type': 'user', 'message': {'content': 'hi'}}]
            path.write_text('\n'.join(json.dumps(r) for r in rows))
            self.assertEqual(SessionTitles().latest_claude(path), 'Review my manuscript references')

    def test_short_real_tasks_are_not_mistaken_for_greetings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session.jsonl'
            path.write_text(json.dumps({'type': 'user', 'message': {'content': '写邮件'}}) + '\n')
            self.assertEqual(SessionTitles().latest_claude(path), '写邮件')

    def test_claude_hook_installation_preserves_other_hooks(self):
        old = json.dumps({'model': 'example', 'hooks': {'UserPromptSubmit': [{'hooks': [{'type': 'command', 'command': 'existing-hook'}]}]}})
        new = claude_config(old, '/test/python3', Path('/test/sidebar'))
        self.assertEqual(json.loads(new)['hooks']['UserPromptSubmit'][0]['hooks'][0]['command'], 'existing-hook')
        self.assertEqual(claude_config(new, '/test/python3', Path('/test/sidebar')), new)
