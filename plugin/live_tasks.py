"""Local session-backed titles and a process-checked Kimi identity fallback."""

import json
from pathlib import Path
import re
import subprocess
import time


def run(herdr, *args):
    result = subprocess.run([herdr, *args], capture_output=True, text=True, timeout=15)
    if result.returncode:
        return None
    return result.stdout


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text")
    return ""


def compact(text):
    return re.sub(r"\s+", "", text)


def prompt_title(text):
    text = re.sub(r"<[^>]+>[\s\S]*?</[^>]+>", "", text)
    text = " ".join(text.split()).strip()
    if len(text) < 6 or text.lower() in {"resume", "continue", "你好", "继续", "可以", "好的"}:
        return None
    return text[:36] + ("…" if len(text) > 36 else "")


def pi_session_title(pane, screen, root=None, raw=False):
    """Match visible assistant text to one session; never guess by file recency."""
    root = root or Path.home() / ".pi/agent/sessions"
    cwd = pane.get("cwd", "")
    # Pi uses this escaped directory for ordinary Unix project paths.
    directory = root / ("--" + re.sub(r"[^a-zA-Z0-9]", "-", cwd.strip("/")) + "--")
    candidates = directory.glob("*.jsonl") if directory.is_dir() else root.glob("*/*.jsonl")
    candidates = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    samples = {compact(line) for line in screen.splitlines() if len(compact(line)) >= 22}
    matches = []
    for path in candidates:
        try:
            if path.stat().st_size > 8_000_000:
                continue
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except (OSError, ValueError):
            continue
        if not rows or rows[0].get("cwd") != cwd:
            continue
        messages = [r["message"] for r in rows if r.get("type") == "message"]
        assistant = compact("\n".join(text_content(m.get("content")) for m in messages[-12:]
                                     if m.get("role") == "assistant"))
        score = sum(sample in assistant for sample in samples)
        if score < 2:
            continue
        title = next(((text_content(m.get("content"))[:1600] if raw else t)
                      for m in reversed(messages) if m.get("role") == "user"
                      and (t := prompt_title(text_content(m.get("content"))))), None)
        if title:
            matches.append((score, title))
    matches.sort(reverse=True)
    if not matches or (len(matches) > 1 and matches[0][0] == matches[1][0]):
        return None
    return matches[0][1]


def kimi_state(screen):
    """Classify only the current bottom UI, avoiding quoted historical text."""
    lines = screen.splitlines()[-22:]
    current = "\n".join(lines)
    if "context:" not in current or not re.search(r"kimi[-\w.]*", current, re.I):
        return None
    if ("↵ confirm" in current and re.search(r"approve|reject|choose", current, re.I)) or (
            "↑↓ select" in current and "esc cancel" in current):
        return "blocked"
    if re.search(r"(?im)^\s*[\u2800-\u28ff]+\s*(?:thinking|working|using)\b", current):
        return "working"
    if re.search(r"(?m)^\s*│\s*>[^\n]*│\s*$", current):
        return "idle"
    return None


def reconcile(herdr, pane, periodic=False, settings=None):
    """Hooks own live states; repair only a missing Kimi identity."""
    if pane.get("agent") == "pi" and (settings is None or settings.pi_titles):
        screen = run(herdr, "pane", "read", pane["pane_id"], "--source", "detection", "--lines", "55")
        if screen:
            title = pi_session_title(pane, screen, Path(settings.pi_sessions) if settings else None)
            if title:
                pane["_live_task"] = title
        return
    if settings is not None and not settings.kimi_compat:
        return
    if (pane.get("agent") and pane.get("agent") != "kimi-local") or not periodic:
        return
    info = run(herdr, "pane", "process-info", "--pane", pane["pane_id"])
    if not info:
        return
    processes = json.loads(info)["result"]["process_info"].get("foreground_processes", [])
    kimi = any(p.get("name") == "kimi" and
               Path(p.get("argv0", "")).name in {"kimi", "kimi-co", "kimi-code"}
               for p in processes)
    if not kimi:
        if pane.get("agent") == "kimi-local":
            run(herdr, "pane", "release-agent", pane["pane_id"],
                "--source", "local.kimi-hook", "--agent", "kimi-local", "--seq", str(time.time_ns()))
            run(herdr, "pane", "report-metadata", pane["pane_id"],
                "--source", "local.kimi-hook", "--clear-display-agent")
            pane.pop("agent", None)
        return
    screen = run(herdr, "pane", "read", pane["pane_id"], "--source", "detection", "--lines", "32")
    state = kimi_state(screen or "")
    if not state:
        return
    # 0.8.2 suppresses known-agent reports without a matching process alias.
    # A custom integration label is supported; metadata supplies the UI name.
    result = run(herdr, "pane", "report-agent", pane["pane_id"], "--source", "local.kimi-hook",
                 "--agent", "kimi-local", "--state", state, "--seq", str(time.time_ns()))
    if result is not None:
        # Herdr may acknowledge a report while ignoring it due to old ownership.
        current = run(herdr, "pane", "get", pane["pane_id"])
        if not current or json.loads(current)["result"]["pane"].get("agent") != "kimi-local":
            return
        run(herdr, "pane", "report-metadata", pane["pane_id"],
            "--source", "local.kimi-hook", "--display-agent", "Kimi Code")
        pane["agent"] = "kimi-local"
        pane["agent_status"] = state
