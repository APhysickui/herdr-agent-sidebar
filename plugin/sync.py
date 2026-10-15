"""Publish task labels, public IDs and readable directories for the sidebar."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from live_tasks import reconcile
from settings import load_settings


def task_title(pane):
    """Use actual app titles, rejecting shell, model and launcher boilerplate."""
    if not pane.get("agent"):
        return None
    title = pane.get("terminal_title_stripped") or pane.get("terminal_title") or ""
    title = " ".join(title.split())
    title = re.sub(r"^[^\w]+", "", title).strip()
    if not title or len(title) > 160 or re.search(r"\S+@\S+:", title):
        return None
    if re.match(r"^(?:codex(?:\s+resume)?|claude(?:\s+code)?|kimi(?:[-\s].*)?|qoder(?:\s+cn)?|terminal|zsh|bash|fish)(?:\s|$)", title, re.I):
        return None
    if re.match(r"^(?:π|pi)\s*(?:[-·]|$)", title, re.I):
        return None
    if title in {"你可以干什么", "你好", "hello", "hi"}:
        return None
    return title


def folder_label(cwd):
    path = Path(cwd or str(Path.home()))
    home = Path.home()
    if path == home:
        return "~"
    for root in (home / "Documents", home / "Desktop", home):
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        return " / ".join(relative.parts[-2:]) if relative.parts else root.name
    return " / ".join(path.parts[-2:])


def sidebar_values(pane):
    cwd = pane.get("foreground_cwd") or pane.get("cwd") or str(Path.home())
    # Native `pane` renders explicit names immediately, even without an event.
    # Only supply a fallback when no explicit title or manual label exists.
    named = pane.get("title") or pane.get("label")
    title = pane.get("_live_task") or pane.get("tokens", {}).get("live_task") or task_title(pane)
    task = None if named else (title or Path(cwd).name)
    if Path(cwd) == Path.home() and not named and not title:
        task = "新任务 / " + (pane.get("agent") or "终端")
    return {"pane_id": pane["pane_id"], "task": task, "folder": folder_label(cwd)}


def event_pane(value):
    """Find the supplied pane snapshot to avoid reading the whole session."""
    if not isinstance(value, dict):
        return None
    if "pane_id" in value and "cwd" in value:
        return value
    for child in value.values():
        found = event_pane(child)
        if found:
            return found
    return None


def main():
    settings = load_settings()
    herdr = os.environ.get("HERDR_BIN_PATH", settings.herdr_binary)
    periodic = "--periodic" in sys.argv[1:]
    if periodic and not Path(os.environ.get("HERDR_SOCKET_PATH", settings.socket_path)).exists():
        return 0
    event = os.environ.get("HERDR_PLUGIN_EVENT_JSON")
    pane = event_pane(json.loads(event)) if event else None
    if pane:
        panes = [pane]
    else:
        result = subprocess.run(
            [herdr, "pane", "list"], capture_output=True, text=True, timeout=15
        )
        if result.returncode:
            if periodic and any(reason in result.stderr.lower() for reason in
                                ("connection refused", "no such file", "server is not running")):
                return 0
            sys.stderr.write(result.stderr)
            return result.returncode
        panes = json.loads(result.stdout)["result"]["panes"]
    for pane in panes:
        reconcile(herdr, pane, periodic=periodic or os.environ.get("HERDR_PLUGIN_EVENT") == "startup", settings=settings)
        values = sidebar_values(pane)
        existing = pane.get("tokens", {})
        changed = {name: value for name, value in values.items()
                   if existing.get(name) != value}
        if not changed:
            continue
        command = [herdr, "pane", "report-metadata", pane["pane_id"],
                   "--source", "local.pane-id"]
        for name, value in changed.items():
            if value is None:
                command.extend(["--clear-token", name])
            else:
                command.extend(["--token", f"{name}={value}"])
        result = subprocess.run(
            command,
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode:
            # A pane can disappear between listing and reporting.
            if '"pane_not_found"' in result.stderr:
                continue
            sys.stderr.write(result.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
