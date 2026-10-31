#!/usr/bin/env python3
"""Install the sidebar with exact backups; Python 3.11+, standard library only."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
PLUGIN_ID = "community.agent-sidebar"
TIMER_ID = "dev.herdr.agent-sidebar"
ROWS = '''[
  ["state_icon", { token = "pane", bold = true, dim = false }, { token = "$task", bold = true, dim = false }],
  ["agent", "$pane_id", "state_text"],
  [{ token = "$folder", dim = true }],
]'''
KIMI_EVENTS = [("SessionStart", "session", None), ("UserPromptSubmit", "working", None),
               ("PreToolUse", "working", "^(?!AskUserQuestion$).*$"),
               ("PreToolUse", "blocked", "^AskUserQuestion$"),
               ("PostToolUse", "working", "^AskUserQuestion$"),
               ("PostToolUseFailure", "working", "^AskUserQuestion$"),
               ("PermissionRequest", "blocked", None), ("PermissionResult", "working", None),
               ("SubagentStart", "working", None), ("PreCompact", "working", None),
               ("Stop", "idle", None), ("Interrupt", "idle", None)]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def table_keys(text, table, values):
    """Replace only requested TOML keys, retaining unrelated sections/comments."""
    if text.strip():
        tomllib.loads(text)
    lines = text.splitlines(keepends=True)
    header = re.compile(r"^\s*\[" + re.escape(table) + r"\]\s*(?:#.*)?$")
    start = next((i for i, line in enumerate(lines) if header.match(line.rstrip())), None)
    if start is None:
        text = text.rstrip() + ("\n\n" if text.strip() else "") + f"[{table}]\n"
        return text + "".join(f"{key} = {value}\n" for key, value in values.items())
    def is_header(line):
        if not line.lstrip().startswith("["):
            return False
        try:
            tomllib.loads(line)
            return True
        except tomllib.TOMLDecodeError:
            return False
    end = next((i for i in range(start + 1, len(lines)) if is_header(lines[i])), len(lines))
    body = lines[start + 1:end]
    for key, value in values.items():
        found = next((i for i, line in enumerate(body) if re.match(r"^\s*" + re.escape(key) + r"\s*=", line)), None)
        replacement = [f"{key} = {value}\n"]
        if found is None:
            body.extend(replacement)
            continue
        stop = found + 1
        while True:
            try:
                tomllib.loads("".join(body[found:stop]))
                break
            except tomllib.TOMLDecodeError:
                if stop >= len(body):
                    raise
                stop += 1
        body[found:stop] = replacement
    result = "".join(lines[:start + 1] + body + lines[end:])
    tomllib.loads(result)
    return result


def kimi_config(text, python, prefix):
    """Append local hooks and retain other integrations and credentials verbatim."""
    parsed = tomllib.loads(text) if text.strip() else {}
    hooks = parsed.get("hooks", [])
    if not isinstance(hooks, list):
        raise ValueError("Expected Kimi's [[hooks]] configuration format")
    if any("herdr-agent-state" in h.get("command", "") or "kimi-state.sh" in h.get("command", "")
           for h in hooks):
        raise ValueError("An existing Herdr/Kimi hook was found. Migrate it first; see docs/troubleshooting.md")
    additions = []
    for event, action, matcher in KIMI_EVENTS:
        command = shlex.join([str(python), str(prefix / "kimi_state.py"), action])
        if any(h.get("event") == event and h.get("command") == command for h in hooks):
            continue
        block = f"\n[[hooks]]\nevent = {json.dumps(event)}\ncommand = {json.dumps(command)}\ntimeout = 2\n"
        if matcher:
            block += f"matcher = {json.dumps(matcher)}\n"
        additions.append(block)
    result = text.rstrip() + "\n" + "".join(additions)
    tomllib.loads(result)
    return result


def manifest(python):
    template = (ROOT / "plugin/herdr-plugin.toml").read_text()
    return template.replace('["python3", "realtime.py", "--once"]', f'[{json.dumps(str(python))}, "realtime.py", "--once"]')


def claude_config(text, python, prefix):
    data = json.loads(text) if text.strip() else {}
    entries = data.setdefault('hooks', {}).setdefault('UserPromptSubmit', [])
    cmd = shlex.join([str(python), str(prefix / 'agent_input.py')])
    if not any(h.get('command') == cmd for entry in entries for h in entry.get('hooks', [])):
        entries.append({'hooks': [{'type': 'command', 'command': cmd, 'timeout': 2}]})
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n'


def timer_plist(prefix, python, socket_path, interval):
    return plistlib.dumps({"Label": TIMER_ID,
                          "ProgramArguments": [str(python), str(prefix / "realtime.py"), "--watch"],
                          "KeepAlive": True, "ThrottleInterval": 5, "RunAtLoad": True, "ProcessType": "Background",
                          "EnvironmentVariables": {"HERDR_SOCKET_PATH": str(socket_path)},
                          "StandardErrorPath": str(prefix / "refresh.log")})


def command(args, check=True):
    return subprocess.run([str(a) for a in args], check=check, capture_output=True, text=True)


def install(args):
    prefix = args.prefix.expanduser().resolve()
    home = Path.home()
    python = Path(sys.executable).resolve()
    herdr = shutil.which(args.herdr)
    if not herdr:
        raise ValueError("herdr was not found; install Herdr or pass --herdr /path/to/herdr")
    config = args.config.expanduser().resolve()
    socket_path = args.socket.expanduser().resolve()
    if prefix == ROOT or ROOT.is_relative_to(prefix):
        raise ValueError("Install outside this source checkout")
    state_path = prefix / "install-state.json"
    if prefix.exists() and any(prefix.iterdir()) and not state_path.exists():
        raise ValueError(f"Nonempty install directory is not owned by this installer: {prefix}")
    state = json.loads(state_path.read_text()) if state_path.exists() else {"version": 1, "files": {}}
    if state.get("timer") and args.no_timer:
        raise ValueError("To remove an existing timer, uninstall before installing with --no-timer")
    writes = {}
    for source in (ROOT / "plugin").glob("*.py"):
        writes[prefix / source.name] = source.read_bytes()
    writes[prefix / "herdr-plugin.toml"] = manifest(python).encode()
    settings = (f"herdr_binary = {json.dumps(herdr)}\nsocket_path = {json.dumps(str(socket_path))}\n"
                f"pi_sessions = {json.dumps(str(home / '.pi/agent/sessions'))}\n"
                f"pi_titles = {str(args.with_pi or state.get('with_pi', False)).lower()}\n"
                f"kimi_compat = {str(args.with_kimi or state.get('with_kimi', False)).lower()}\n"
                f"auto_tabs = {str(getattr(args, 'auto_tabs', False) or state.get('auto_tabs', False)).lower()}\n"
                f"adopt_tabs = {str(getattr(args, 'auto_tabs', False) or state.get('auto_tabs', False)).lower()}\n"
                f"poll_seconds = {args.interval}\n")
    writes[prefix / "settings.toml"] = settings.encode()
    existing = config.read_text() if config.exists() else ""
    writes[config] = table_keys(existing, "ui.sidebar.agents", {"rows": ROWS}).encode()
    if args.with_pi or state.get("with_pi", False):
        writes[home / ".pi/agent/extensions/herdr-sidebar-task-title.ts"] = (ROOT / "extensions/pi-task-title.ts").read_bytes()
    if args.with_kimi or state.get("with_kimi", False):
        path = home / ".kimi-code/config.toml"
        writes[path] = kimi_config(path.read_text() if path.exists() else "", python, prefix).encode()
    if getattr(args, 'with_claude', False) or state.get('with_claude', False):
        path = home / '.claude/settings.json'
        writes[path] = claude_config(path.read_text() if path.exists() else '', python, prefix).encode()
    timer = sys.platform == "darwin" and not args.no_timer
    if timer:
        writes[home / "Library/LaunchAgents" / f"{TIMER_ID}.plist"] = timer_plist(prefix, python, socket_path, args.interval)
    if args.dry_run:
        print("Plan only; no files or runtime state changed:")
        for path in writes:
            print(f"  write {path}")
        print(f"  link {PLUGIN_ID}; timer={timer}; interval={args.interval}s")
        return
    prefix.mkdir(parents=True, exist_ok=True)
    for path, data in writes.items():
        key = str(path)
        if key not in state["files"]:
            state["files"][key] = {"original": base64.b64encode(path.read_bytes()).decode() if path.exists() else None}
        state["files"][key]["installed_sha256"] = digest(data)
    state.update({"herdr": herdr, "timer": timer, "with_pi": args.with_pi or state.get("with_pi", False),
                  "with_kimi": args.with_kimi or state.get("with_kimi", False),
                  "auto_tabs": getattr(args, 'auto_tabs', False) or state.get('auto_tabs', False)})
    state['with_claude'] = getattr(args, 'with_claude', False) or state.get('with_claude', False)
    # Save recovery information before writing anything else.
    state_path.write_text(json.dumps(state, indent=2))
    state_path.chmod(0o600)
    for path, data in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        # Backups may contain existing credentials; restrict managed config copies.
        if path in (config, home / ".kimi-code/config.toml", home / '.claude/settings.json'):
            path.chmod(0o600)
    if args.no_activate:
        print(f"Files installed to {prefix}; runtime activation skipped.")
        return
    command([herdr, "plugin", "link", prefix, "--enabled"])
    command([herdr, "server", "reload-config"], check=False)
    env = dict(os.environ, HERDR_SOCKET_PATH=str(socket_path))
    subprocess.run([str(python), str(prefix / "realtime.py"), "--once"], env=env, check=True)
    if timer:
        target = f"gui/{os.getuid()}"
        command(["launchctl", "bootout", f"{target}/{TIMER_ID}"], check=False)
        command(["launchctl", "bootstrap", target, home / "Library/LaunchAgents" / f"{TIMER_ID}.plist"])
    print(f"Installed {PLUGIN_ID} at {prefix}")
    print("Manual names stay fixed; clear a pane label to enable automatic naming.")


def uninstall(args):
    prefix = args.prefix.expanduser().resolve()
    state_path = prefix / "install-state.json"
    if not state_path.exists():
        raise ValueError(f"No install state found at {prefix}")
    state = json.loads(state_path.read_text())
    conflicts = [path for path, record in state["files"].items()
                 if not Path(path).exists() or digest(Path(path).read_bytes()) != record["installed_sha256"]]
    if conflicts:
        raise ValueError("Files changed after installation; nothing was removed. Back up and reconcile these first:\n" + "\n".join(conflicts))
    if args.dry_run:
        print("Would unregister the plugin/timer and restore these files:")
        print("\n".join(state["files"]))
        return
    if not args.no_activate:
        if state.get("timer") and sys.platform == "darwin":
            command(["launchctl", "bootout", f"gui/{os.getuid()}/{TIMER_ID}"], check=False)
        command([state["herdr"], "plugin", "unlink", PLUGIN_ID], check=False)
    for path, record in state["files"].items():
        path = Path(path)
        if record["original"] is None:
            path.unlink()
        else:
            path.write_bytes(base64.b64decode(record["original"]))
    state_path.unlink()
    if not args.no_activate:
        command([state["herdr"], "server", "reload-config"], check=False)
    print("Uninstalled; original managed files restored.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=Path.home() / ".local/share/herdr-agent-sidebar")
    parser.add_argument("--config", type=Path, default=Path.home() / ".config/herdr/config.toml")
    parser.add_argument("--socket", type=Path, default=Path.home() / ".config/herdr/herdr.sock")
    parser.add_argument("--herdr", default="herdr")
    parser.add_argument("--interval", type=float, default=2.0, help="Session file fallback interval in seconds")
    parser.add_argument("--auto-tabs", action="store_true", help="Adopt existing tabs for automatic task names")
    parser.add_argument("--with-pi", action="store_true")
    parser.add_argument("--with-kimi", action="store_true")
    parser.add_argument("--with-claude", action="store_true", help="Capture Claude task input with per-session metadata")
    parser.add_argument("--no-timer", action="store_true")
    parser.add_argument("--no-activate", action="store_true", help="Write files without linking or starting services")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error("--interval must be at least 0.5 seconds")
    try:
        (uninstall if args.uninstall else install)(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
