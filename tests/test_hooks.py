import json
import unittest
from kimi_state import requests_for


class KimiHookTests(unittest.TestCase):
    def test_all_lifecycle_events_include_identity_and_display_name(self):
        for action, state in [('session', 'idle'), ('working', 'working'), ('blocked', 'blocked'), ('idle', 'idle')]:
            with self.subTest(action=action):
                state_request, metadata_request = requests_for(action, 'test:p1', 'session-test', seq=100)
                self.assertEqual(state_request['params']['agent'], 'kimi-local')
                self.assertEqual(state_request['params']['source'], 'local.kimi-hook')
                self.assertEqual(state_request['params']['state'], state)
                self.assertEqual(state_request['params']['agent_session_id'], 'session-test')
                self.assertEqual(metadata_request['params']['display_agent'], 'Kimi Code')

    def test_startup_does_not_need_a_session_id_to_register_identity(self):
        request, _ = requests_for('session', 'test:p1', None, seq=101)
        self.assertNotIn('agent_session_id', request['params'])
        self.assertEqual(request['params']['state'], 'idle')

    def test_unknown_actions_are_ignored(self):
        self.assertEqual(requests_for('invalid', 'test:p1'), [])
