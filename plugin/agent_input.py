"""Capture a Claude prompt as input metadata; never publish it as a title."""
import json
import os
import socket
import sys
import time


def request_for(payload, pane):
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    tokens = {"live_task": prompt.strip()[:480], "task_agent": "claude"}
    for field, key in (("session_id", "task_session"), ("transcript_path", "task_file")):
        value = payload.get(field)
        if isinstance(value, str) and value:
            tokens[key] = value
    return {"id": "sidebar:claude-input", "method": "pane.report_metadata",
            "params": {"pane_id": pane, "source": "local.claude-input", "seq": time.time_ns(), "tokens": tokens}}


def main():
    endpoint, pane = os.environ.get("HERDR_SOCKET_PATH"), os.environ.get("HERDR_PANE_ID")
    if os.environ.get("HERDR_ENV") != "1" or not endpoint or not pane:
        return 0
    try:
        payload = json.load(sys.stdin)
        request = request_for(payload, pane) if isinstance(payload, dict) else None
        if request:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.5)
                client.connect(endpoint)
                client.sendall((json.dumps(request) + "\n").encode())
                client.recv(16384)
    except (OSError, ValueError):
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
