#!/usr/bin/env python3
"""Fake event sender — sends test events to the overlay for testing.

Usage:
    python3 test_events.py [--url http://127.0.0.1:5731/event/]

Sends a sequence of state transitions simulating a full interaction cycle.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from event_schema import build_event


def send_event(url: str, event: dict) -> dict:
    """Send an event and return the response."""
    data = json.dumps(event).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"status": "error", "message": f"Connection failed: {e.reason}"}


def send_sequence(url: str, delay: float = 2.0) -> None:
    """Send a sequence of events simulating a full interaction."""
    steps = [
        ("state_change", "idle", {}),
        ("state_change", "listening", {"previous_state": "idle"}),
        ("state_change", "thinking", {"previous_state": "listening"}),
        ("message_chunk", "thinking", {"text": "根据您的要求，我已经检查了配置文件...", "index": 0, "final": False}),
        ("message_chunk", "thinking", {"text": "相关配置如下：1. 数据库连接正常", "index": 1, "final": True}),
        ("tool_start", "tool_running", {"tool_name": "bash", "arguments": "ls -la /home/user"}),
        ("tool_result", "thinking", {"tool_name": "bash", "success": True, "exit_code": 0}),
        ("state_change", "thinking", {"previous_state": "tool_running"}),
        ("state_change", "waiting_for_jack", {"previous_state": "thinking"}),
        ("state_change", "thinking", {"previous_state": "waiting_for_jack"}),
        ("state_change", "done", {"previous_state": "thinking"}),
        ("state_change", "idle", {"previous_state": "done"}),
    ]

    print(f"Sending {len(steps)} events to {url}...")
    for event_type, state, payload in steps:
        event = build_event(event_type, state, payload)
        resp = send_event(url, event)
        status = "✓" if resp.get("status") == "ok" else "✗"
        print(f"  {status} {state} ({event_type})")
        time.sleep(delay)

    print("Sequence complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send fake events to Hermes Pet overlay")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5731/event/",
        help="Overlay event URL",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds between events",
    )
    parser.add_argument(
        "--event-type",
        choices=["state_change", "heartbeat", "error_occurred", "reset"],
        help="Send a single event type and exit",
    )
    parser.add_argument(
        "--state",
        choices=["idle", "listening", "thinking", "tool_running",
                 "waiting_for_jack", "done", "error", "unknown"],
        help="State for single event",
    )
    args = parser.parse_args()

    if args.event_type and args.state:
        event = build_event(args.event_type, args.state)
        resp = send_event(args.url, event)
        print(json.dumps(resp, indent=2))
    elif args.event_type:
        print("--state is required with --event-type")
        sys.exit(1)
    else:
        send_sequence(args.url, delay=args.delay)


if __name__ == "__main__":
    import sys
    main()
