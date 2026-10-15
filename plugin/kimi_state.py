"""Receive Kimi lifecycle hooks and report them to Herdr over a local socket."""
import json
import os
import socket
import sys
import time


def requests_for(action, pane, session_id=None, seq=None):
    if action not in {"session", "working", "blocked", "idle"}:
        return []
    seq = seq or time.time_ns()
    params = {"pane_id": pane, "source": "local.kimi-hook", "agent": "kimi-local",
              "seq": seq, "state": "idle" if action == "session" else action}
    if isinstance(session_id, str) and session_id:
        params["agent_session_id"] = session_id
    return [
        {"id": f"local.kimi-state:{seq}", "method": "pane.report_agent", "params": params},
        {"id": f"local.kimi-label:{seq}", "method": "pane.report_metadata",
         "params": {"pane_id": pane, "source": "local.kimi-hook", "display_agent": "Kimi Code"}},
    ]


def main():
    if os.environ.get("HERDR_ENV") != "1":
        return 0
    endpoint, pane = os.environ.get("HERDR_SOCKET_PATH"), os.environ.get("HERDR_PANE_ID")
    if not endpoint or not pane:
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    for request in requests_for(action, pane, payload.get("session_id")):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.5)
                client.connect(endpoint)
                client.sendall((json.dumps(request) + "\n").encode())
                reply = client.recv(16384)
                if reply and json.loads(reply).get("error"):
                    print("Herdr rejected the Kimi state hook.", file=sys.stderr)
        except (OSError, ValueError):
            # Hook failures must not prevent the user from using Kimi.
            continue
    return 0


if __name__ == "__main__":
    sys.exit(main())
