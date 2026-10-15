import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import sync
from settings import load_settings


class RuntimeTests(unittest.TestCase):
    def test_no_metadata_writes_when_nothing_changed(self):
        pane = {'pane_id': 'test:p1', 'agent': 'codex', 'cwd': '/tmp/project'}
        pane['tokens'] = sync.sidebar_values(pane)
        result = Mock(returncode=0, stdout=json.dumps({'result': {'panes': [pane]}}))
        with patch('sys.argv', ['sync.py']), patch.dict(os.environ, {}, clear=True), \
             patch('sync.reconcile'), patch('sync.subprocess.run', return_value=result) as command:
            self.assertEqual(sync.main(), 0)
        self.assertEqual(command.call_count, 1)

    def test_settings_expand_home_and_kimi_is_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.toml'
            path.write_text('socket_path = "~/my-herdr.sock"\n')
            with patch.dict(os.environ, {'HERDR_SIDEBAR_CONFIG': str(path)}):
                settings = load_settings()
            self.assertEqual(settings.socket_path, str(Path.home()/'my-herdr.sock'))
            self.assertFalse(settings.kimi_compat)

    def test_unknown_settings_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'settings.toml'
            path.write_text('typo = true\n')
            with patch.dict(os.environ, {'HERDR_SIDEBAR_CONFIG': str(path)}), self.assertRaises(ValueError):
                load_settings()
