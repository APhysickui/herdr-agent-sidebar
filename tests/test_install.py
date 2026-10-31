import argparse
import json
import os
from pathlib import Path
import plistlib
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import install


class InstallTests(unittest.TestCase):
    def test_multiline_rows_and_other_settings_survive(self):
        old = '''# My theme
[ui]
agent_panel_sort = "priority"
sidebar_width = 40
[ui.sidebar.agents]
row_gap = 1
rows = [
  ["agent"],
  ["tab", "pane"],
]
[ui.toast]
delivery = "off"
'''
        new = install.table_keys(old, "ui.sidebar.agents", {"rows": install.ROWS})
        parsed = tomllib.loads(new)
        self.assertEqual(parsed["ui"]["sidebar"]["agents"]["row_gap"], 1)
        self.assertEqual(parsed["ui"]["sidebar_width"], 40)
        self.assertEqual(parsed["ui"]["toast"]["delivery"], "off")
        self.assertIn("# My theme", new)
        self.assertEqual(install.table_keys(new, "ui.sidebar.agents", {"rows": install.ROWS}), new)

    def test_append_missing_table(self):
        old = '[keys]\nprefix = "ctrl+a"\n'
        new = install.table_keys(old, "ui.sidebar.agents", {"rows": install.ROWS})
        self.assertEqual(tomllib.loads(new)["keys"]["prefix"], "ctrl+a")

    def test_kimi_preserves_existing_hooks_and_quotes_paths(self):
        old = 'default_model = "my-model"\n[[hooks]]\nevent = "Stop"\ncommand = "my-existing-hook"\n'
        prefix = Path('/tmp/path with spaces/sidebar')
        new = install.kimi_config(old, '/tmp/python path/python3', prefix)
        parsed = tomllib.loads(new)
        self.assertEqual(parsed["hooks"][0]["command"], "my-existing-hook")
        self.assertEqual(parsed["default_model"], "my-model")
        self.assertEqual(len(parsed["hooks"]), 1 + len(install.KIMI_EVENTS))
        self.assertIn("'/tmp/python path/python3'", parsed["hooks"][1]["command"])
        self.assertEqual(install.kimi_config(new, '/tmp/python path/python3', prefix), new)

    def test_existing_official_kimi_hooks_require_migration(self):
        old = '[[hooks]]\nevent = "Stop"\ncommand = "sh /tmp/herdr-agent-state.sh idle"\n'
        with self.assertRaisesRegex(ValueError, "existing Herdr/Kimi"):
            install.kimi_config(old, '/usr/bin/python3', Path('/tmp/sidebar'))

    def test_generated_paths_are_resolved_for_launchd(self):
        data = plistlib.loads(install.timer_plist(Path('/tmp/a b'), '/tmp/python3', '/tmp/a.sock', 90))
        self.assertEqual(data["ProgramArguments"][1], '/tmp/a b/realtime.py')
        self.assertTrue(data["KeepAlive"])
        self.assertNotIn('StartInterval', data)
        self.assertEqual(data["EnvironmentVariables"]["HERDR_SOCKET_PATH"], '/tmp/a.sock')

    def args(self, home):
        return argparse.Namespace(prefix=home/'installed', config=home/'.config/herdr/config.toml',
            socket=home/'test.sock', herdr='herdr', with_pi=True, with_kimi=True, no_timer=True,
            interval=60, dry_run=False, no_activate=True)

    def test_install_reinstall_uninstall_roundtrip_in_temporary_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            args = self.args(home)
            args.config.parent.mkdir(parents=True)
            original = b'[keys]\nprefix = "ctrl+a"\n'
            args.config.write_bytes(original)
            with patch('pathlib.Path.home', return_value=home), patch('shutil.which', return_value='/tmp/herdr'):
                install.install(args)
                installed = args.config.read_bytes()
                self.assertNotEqual(installed, original)
                self.assertEqual(os.stat(args.prefix/'install-state.json').st_mode & 0o777, 0o600)
                install.install(args)
                self.assertEqual(args.config.read_bytes(), installed)
                install.uninstall(args)
            self.assertEqual(args.config.read_bytes(), original)
            self.assertFalse((home/'.kimi-code/config.toml').exists())
            self.assertFalse((home/'.pi/agent/extensions/herdr-sidebar-task-title.ts').exists())

    def test_uninstall_refuses_later_user_edits_without_removing_anything(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            args = self.args(home)
            with patch('pathlib.Path.home', return_value=home), patch('shutil.which', return_value='/tmp/herdr'):
                install.install(args)
                args.config.write_text(args.config.read_text() + '\n# User edit\n')
                with self.assertRaisesRegex(ValueError, 'nothing was removed'):
                    install.uninstall(args)
            self.assertTrue((args.prefix/'sync.py').exists())
            self.assertIn('# User edit', args.config.read_text())


if __name__ == '__main__':
    unittest.main()
