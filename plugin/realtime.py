"""Event-driven task labels with a two-second local-session fallback."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import sqlite3
import sys
import time

from live_tasks import prompt_title, pi_session_title, reconcile
from settings import load_settings
from sync import sidebar_values
from summaries import Summaries, compact_cells


def task_input(text):
    return " ".join(text.split())[:1600] if prompt_title(text) else None


class API:
    def __init__(self, endpoint):
        self.endpoint = str(endpoint)

    def call(self, method, **params):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(2)
            client.connect(self.endpoint)
            client.sendall((json.dumps({"id": "sidebar", "method": method, "params": params}) + "\n").encode())
            data = b""
            while b"\n" not in data:
                chunk = client.recv(65536)
                if not chunk:
                    raise OSError("Herdr closed the connection")
                data += chunk
            result = json.loads(data.split(b"\n", 1)[0])
            if "error" in result:
                raise ValueError(str(result["error"]))
            return result["result"]

    def subscribe(self):
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2)
        try:
            client.connect(self.endpoint)
            events = ["pane.created", "pane.closed", "pane.updated", "pane.focused", "pane.moved",
                      "pane.agent_detected", "tab.created", "tab.closed",
                      "tab.focused", "tab.renamed", "layout.updated"]
            client.sendall((json.dumps({"id": "sidebar-watch", "method": "events.subscribe",
                                       "params": {"subscriptions": [{"type": event} for event in events]}}) + "\n").encode())
            data = b""
            while b"\n" not in data:
                chunk = client.recv(65536)
                if not chunk:
                    raise OSError("Herdr closed the event subscription")
                data += chunk
            reply = json.loads(data.split(b"\n", 1)[0])
            if "error" in reply:
                raise ValueError(str(reply["error"]))
            client.setblocking(False)
            return client
        except Exception:
            client.close()
            raise


def short(text, size=24):
    text = " ".join(text.split())
    return text[:size] + ("…" if len(text) > size else "")


class SessionTitles:
    def __init__(self, home=None):
        self.home = home or Path.home()
        self.paths = {}
        self.cache = {}

    def latest_claude(self, path):
        try:
            path = Path(path)
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            cached = self.cache.get(str(path))
            if cached and cached[0] == signature:
                return cached[1]
            with path.open('rb') as file:
                offset = max(0, stat.st_size - 1_000_000)
                file.seek(offset)
                if offset:
                    file.readline()
                lines = file.read().splitlines()
            title = None
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if record.get('type') != 'user' or record.get('isMeta'):
                    continue
                content = record.get('message', {}).get('content', '')
                if isinstance(content, list):
                    content = ' '.join(item.get('text', '') for item in content if item.get('type') == 'text')
                if not isinstance(content, str) or content.lstrip().startswith(('<local-command', '<command-name>', '<system-reminder>')):
                    continue
                title = task_input(content)
                if title:
                    break
            self.cache[str(path)] = (signature, title)
            return title
        except OSError:
            return None

    def claude_title(self, pane, api):
        tokens = pane.get('tokens', {})
        session = (pane.get('agent_session') or {}).get('value')
        if tokens.get('task_agent') == 'claude':
            session = tokens.get('task_session') or session
            pane['_task_session'] = session
            if tokens.get('live_task'):
                return task_input(tokens['live_task'])
        if not session:
            info = api.call('pane.process_info', pane_id=pane['pane_id'])['process_info']
            for process in info.get('foreground_processes', []):
                if 'claude' not in process.get('name', '').lower():
                    continue
                path = self.home / '.claude/sessions' / f"{process['pid']}.json"
                try:
                    record = json.loads(path.read_text())
                    if record.get('cwd') == pane.get('cwd'):
                        session = record.get('sessionId')
                        break
                except (OSError, ValueError):
                    continue
        if not session or Path(session).name != session:
            return None
        pane['_task_session'] = session
        candidates = list((self.home / '.claude/projects').glob(f'*/{session}.jsonl'))
        if len(candidates) == 1:
            return self.latest_claude(candidates[0])
        return None

    def latest_codex(self, path):
        path = Path(path)
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            cached = self.cache.get(str(path))
            if cached and cached[0] == signature:
                return cached[1]
            with path.open("rb") as file:
                offset = max(0, stat.st_size - 2_000_000)
                file.seek(offset)
                if offset:
                    file.readline()
                lines = file.read().splitlines()
            title = None
            for line in reversed(lines):
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                payload = record.get("payload", {})
                if record.get("type") == "event_msg" and payload.get("type") == "user_message":
                    title = task_input(payload.get("message", ""))
                    if title:
                        break
                if record.get("type") == "response_item" and payload.get("role") == "user":
                    content = payload.get("content", [])
                    text = " ".join(item.get("text", "") for item in content
                                    if item.get("type") in {"input_text", "text"})
                    if text.lstrip().startswith(("<environment_context>", "# AGENTS.md", "<turn_aborted>",
                                                  "<send_user_message_question_reply>")):
                        continue
                    title = task_input(text)
                    if title:
                        break
            self.cache[str(path)] = (signature, title)
            return title
        except OSError:
            return None

    def codex_path(self, pane, api):
        # Use an explicit reported session when available. Otherwise match the
        # visible footer name uniquely to the local thread index for this cwd.
        session = pane.get("agent_session") or {}
        try:
            database = self.home / ".codex/state_5.sqlite"
            with sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=0.2) as db:
                columns = {r[1] for r in db.execute("pragma table_info(threads)")}
                name = "name" if "name" in columns else "title"
                if session.get("kind") == "id":
                    rows = db.execute(f"select rollout_path, {name} from threads where id=?", (session.get("value"),)).fetchall()
                    if len(rows) == 1:
                        pane["_summary_context"] = rows[0][1] or ""
                    return rows[0][0] if len(rows) == 1 else None
                screen = api.call("pane.read", pane_id=pane["pane_id"], source="detection", lines=6).get("read", {})
                if isinstance(screen, dict):
                    screen = screen.get("content", screen.get("text", ""))
                rows = db.execute(f"select rollout_path, {name} from threads where cwd=? and archived=0 order by updated_at desc limit 100",
                                  (pane.get("cwd"),)).fetchall()
                pieces = [piece.strip() for line in screen.splitlines() for piece in line.split("·")]
                def matches_name(title):
                    return any(title == piece or (
                        len(piece.rstrip(".… ")) >= 8 and piece.endswith(("…", "..."))
                        and title.startswith(piece.rstrip(".… "))
                    ) for piece in pieces)
                matches = [(path, title) for path, title in rows if title and matches_name(title) and Path(path).is_file()]
                if len(matches) == 1:
                    pane["_summary_context"] = matches[0][1]
                    return matches[0][0]
        except (OSError, sqlite3.Error, ValueError, TypeError):
            pass
        return None

    def kimi_title(self, pane):
        session = (pane.get("agent_session") or {}).get("value", "")
        if not session or Path(session).name != session:
            return None
        matches = list((self.home / ".kimi-code/sessions").glob(f"*/{session}/state.json"))
        if len(matches) != 1:
            return None
        try:
            data = json.loads(matches[0].read_text())
            pane["_summary_context"] = data.get("title", "")[:160]
            return task_input(data.get("lastPrompt", ""))
        except (OSError, ValueError):
            return None

    def resolve(self, pane, api):
        if pane.get('agent') == 'claude':
            return self.claude_title(pane, api)
        if pane.get("agent") == "pi":
            live = pane.get("tokens", {}).get("live_task")
            if live:
                return live
            screen = api.call("pane.read", pane_id=pane["pane_id"], source="detection", lines=55)["read"]["text"]
            cache_key = (pane.get("terminal_id"), screen)
            cached = self.cache.get("pi:" + pane["pane_id"])
            if cached and cached[0] == cache_key:
                return cached[1]
            title = pi_session_title(pane, screen, self.home / ".pi/agent/sessions", raw=True)
            self.cache["pi:" + pane["pane_id"]] = (cache_key, title)
            return title
        if pane.get("agent") == "codex":
            path = self.codex_path(pane, api)
            if path:
                return self.latest_codex(path)
        if pane.get("agent") in {"kimi", "kimi-local"}:
            return self.kimi_title(pane)
        if pane.get("agent") == "opencode":
            title = pane.get("terminal_title_stripped", "")
            if title.startswith("OC | "):
                return title[5:].strip()
        return None


def tab_name(tab, panes, max_cells=16):
    members = [p for p in panes if p["tab_id"] == tab["tab_id"]]
    # An idle shell is not a competing task. Display actual agent work when
    # present; tabs containing only shells still use their project directories.
    agents = [p for p in members if p.get("agent")]
    if agents:
        members = agents
    members.sort(key=lambda p: (not bool(p.get("agent")), not p.get("focused"), p["pane_id"]))
    names = []
    for pane in members:
        name = pane.get("title") or pane.get("label") or pane.get("_tab_task") or pane.get("tokens", {}).get("task")
        if name and not pane.get("agent") and not (pane.get("title") or pane.get("label")):
            if not name.startswith("新任务") and not name.endswith("终端"):
                name += "终端"
        if name and name not in names:
            names.append(name)
    if not names:
        return None
    labels = []
    for name in names:
        label = name.replace("新任务 / 终端", "终端").replace("新任务 / pi", "Pi 会话").replace("新任务 / ", "")
        if label not in labels:
            labels.append(label)
    # The top bar identifies the main project. Detailed per-pane tasks belong
    # in the sidebar; joining every task here makes the bar overflow quickly.
    return compact_cells(labels[0], max_cells)


class Engine:
    def __init__(self, api, state, titles=None, auto_tabs=False, adopt_tabs=False, settings=None):
        self.api = api
        self.state = state
        self.titles = titles or SessionTitles()
        self.auto_tabs = auto_tabs
        self.adopt_tabs = adopt_tabs
        self.settings = settings
        self.summaries = Summaries(state, settings) if settings and settings.summarize_titles else None
        self.last_inputs = {}

    def refresh(self):
        snapshot = self.api.call("session.snapshot")["snapshot"]
        panes = snapshot["panes"]
        writes = 0
        for pane in panes:
            if self.settings and self.settings.kimi_compat and pane.get("agent") != "pi":
                reconcile(self.settings.herdr_binary, pane, periodic=True, settings=self.settings)
            title = self.titles.resolve(pane, self.api) if not (
                self.settings and not self.settings.pi_titles and pane.get("agent") == "pi") else None
            identity = (pane.get("terminal_id", pane["pane_id"]), pane.get('agent'),
                        pane.get('_task_session') or pane.get('tokens', {}).get('task_session')
                        or (pane.get('agent_session') or {}).get('value'))
            if title:
                self.last_inputs[identity] = (title, pane.get("_summary_context", ""))
            elif pane.get("agent") and identity in self.last_inputs:
                title, pane["_summary_context"] = self.last_inputs[identity]
            if title and self.summaries:
                summary = self.summaries.get(pane, title)
                title, pane["_tab_task"] = summary["pane"], summary["tab"]
            if title:
                pane["_live_task"] = title
            elif pane.get('agent') in {'claude', 'pi'}:
                # Empty/greeting-only conversations still need distinct labels.
                suffix = (pane.get('_task_session') or pane['pane_id']).split('-')[0][-6:]
                brand = 'Claude' if pane['agent'] == 'claude' else 'Pi'
                pane['_live_task'] = f'{brand} 会话 {suffix}'
            values = sidebar_values(pane)
            existing = pane.setdefault("tokens", {})
            changed = {key: value for key, value in values.items() if existing.get(key) != value}
            if changed:
                self.api.call("pane.report_metadata", pane_id=pane["pane_id"], source="local.pane-id", seq=time.time_ns(), tokens=changed)
                for key, value in changed.items():
                    if value is None:
                        existing.pop(key, None)
                    else:
                        existing[key] = value
                writes += 1
        if self.auto_tabs:
            managed = self.state.setdefault("tabs", {})
            for tab in snapshot["tabs"]:
                previous = managed.get(tab["tab_id"])
                if previous and tab["label"] != previous.get("last"):
                    previous["manual"] = True
                if previous and previous.get("manual"):
                    continue
                if previous is None:
                    if not self.adopt_tabs:
                        continue
                    previous = managed[tab["tab_id"]] = {"original": tab["label"], "last": tab["label"]}
                desired = tab_name(tab, panes, self.settings.tab_max_cells if self.settings else 16)
                if desired and desired != tab["label"]:
                    self.api.call("tab.rename", tab_id=tab["tab_id"], label=desired)
                    previous["last"] = desired
                    writes += 1
        if self.summaries:
            self.summaries.flush()
        self.state['refresh_status'] = {'completed_at': int(time.time()), 'panes': len(panes)}
        return writes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--periodic", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    endpoint = os.environ.get("HERDR_SOCKET_PATH", settings.socket_path)
    key = hashlib.sha256(endpoint.encode()).hexdigest()[:12]
    state_path = Path(__file__).with_name(f"realtime-{key}.json")
    with state_path.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        try:
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
        except ValueError:
            state = {}
        api = API(endpoint)
        engine = Engine(api, state, auto_tabs=settings.auto_tabs, adopt_tabs=settings.adopt_tabs, settings=settings)
        events = None
        interval = max(0.5, settings.poll_seconds)
        due = time.monotonic()
        while True:
            now = time.monotonic()
            if now >= due:
                try:
                    engine.refresh()
                    serialized = json.dumps(state, ensure_ascii=False)
                    if not state_path.exists() or state_path.read_text() != serialized:
                        state_path.write_text(serialized)
                        state_path.chmod(0o600)
                    if args.watch and events is None:
                        events = api.subscribe()
                except (OSError, ValueError) as error:
                    if events:
                        events.close()
                        events = None
                    if not args.watch:
                        print(str(error), file=sys.stderr)
                        return 1
                due = time.monotonic() + interval
            if not args.watch:
                return 0
            if events:
                ready, _, _ = select.select([events], [], [], max(0, due - time.monotonic()))
                if ready:
                    try:
                        data = events.recv(65536)
                        if not data:
                            raise OSError("event stream closed")
                        # Coalesce bursts; a self-generated metadata event causes
                        # at most one no-op pass, never another metadata write.
                        due = min(due, time.monotonic() + 0.25)
                    except OSError:
                        events.close()
                        events = None
            else:
                time.sleep(min(interval, 2))


if __name__ == "__main__":
    sys.exit(main())
