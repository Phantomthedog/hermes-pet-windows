"""Bridge Watcher — Polls Hermes state.db and emits events to Windows overlay.

Usage:
    python3 bridge_watcher.py [--overlay-url http://127.0.0.1:5731] [--db-path <path>]

Reads the phantom profile state.db every second, infers agent state, and
sends state_change events to the Windows overlay via HTTP POST.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

from event_schema import build_event, validate_pet_event
from state_mapper import (
    DEFAULT_IDLE_THRESHOLD_SECONDS,
    LIVE_STATE_FRESHNESS_SECONDS,
    LIVE_STATE_PRIORITY,
    STATE_DONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_THINKING,
    STATE_TOOL_RUNNING,
    STATE_UNKNOWN,
    StateDBError,
    get_live_states,
    get_new_messages,
    get_recent_messages,
    get_session_snapshot,
    has_session_just_ended,
    infer_global_state,
)

DEFAULT_DB_PATH = Path.home() / ".hermes" / "profiles" / "phantom" / "state.db"
DEFAULT_OVERLAY_URL = "http://127.0.0.1:5731/event/"
DEFAULT_POLL_INTERVAL = 1.0
DEFAULT_HEARTBEAT_INTERVAL = 5.0
STATE_FILE = Path(__file__).parent / "bridge_watcher_state.json"


def load_state() -> dict[str, Any]:
    """Load persisted watcher state from JSON file."""
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_state(state: dict[str, Any]) -> None:
    """Persist watcher state to JSON file."""
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n"
        )
    except OSError as e:
        print(f"Warning: Could not save state: {e}", file=sys.stderr)


def send_event(overlay_url: str, event: dict) -> bool:
    """Send an event to the Windows overlay.

    Uses http.client directly instead of urllib.request to avoid
    IncompleteRead issues with Connection: close responses.

    Returns True if the overlay accepted the event, False otherwise.
    """
    import http.client
    from urllib.parse import urlparse

    try:
        parsed = urlparse(overlay_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 5731
        path = parsed.path or "/event/"

        data = json.dumps(event).encode("utf-8")
        conn = http.client.HTTPConnection(host, port, timeout=2)
        conn.request("POST", path, data, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        result = json.loads(body)
        conn.close()
        return result.get("status") == "ok"
    except Exception:
        return False


def _merge_messages_by_id(*message_lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge message rows without duplicating IDs, preserving ascending ID order."""
    merged: dict[int, dict[str, Any]] = {}
    orphan_offset = -1
    for messages in message_lists:
        for msg in messages:
            msg_id = msg.get("id")
            if isinstance(msg_id, int):
                merged[msg_id] = msg
            else:
                merged[orphan_offset] = msg
                orphan_offset -= 1
    return [merged[key] for key in sorted(merged)]


def _fast_forward(db_path: str, last_seen_id: int, max_gap: int = 1000) -> int:
    """If the gap between last_seen_id and MAX(id) is large, fast-forward.

    Avoids slowly crawling through thousands of old messages on startup.
    Skips to 100 IDs behind the latest message.
    """
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute("SELECT MAX(id) FROM messages")
        max_id = cur.fetchone()[0]
        conn.close()
        if max_id is not None and (max_id - last_seen_id) > max_gap:
            new_id = max(max_id - 100, 0)
            print(f"  Fast-forward: {last_seen_id} → {new_id}")
            return new_id
    except (sqlite3.Error, FileNotFoundError, PermissionError):
        pass
    return last_seen_id


def run_watcher(
    db_path: str | Path = DEFAULT_DB_PATH,
    overlay_url: str = DEFAULT_OVERLAY_URL,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL,
    one_shot: bool = False,
) -> None:
    """Main watcher loop.

    Args:
        db_path: Path to Hermes state.db.
        overlay_url: URL of the Windows overlay event endpoint.
        poll_interval: Seconds between polls.
        heartbeat_interval: Seconds between idle heartbeats.
        one_shot: If True, poll once and exit.
    """
    state = load_state()
    last_seen_id = state.get("last_seen_id", 0)
    last_heartbeat_time = state.get("last_heartbeat_time", 0.0)

    # If starting far behind, fast-forward to recent messages
    if last_seen_id == 0:
        last_seen_id = _fast_forward(str(db_path), last_seen_id)

    # Track previous state to avoid duplicate events
    current_state: Optional[str] = None
    previous_snapshot: Optional[dict] = state.get("db_snapshot")

    print(f"Bridge Watcher started")
    print(f"  DB: {db_path}")
    print(f"  Overlay: {overlay_url}")
    print(f"  Last seen message ID: {last_seen_id}")
    print(f"  Poll interval: {poll_interval}s")
    print(f"  Heartbeat interval: {heartbeat_interval}s")

    while True:
        try:
            (current_state, previous_snapshot,
             last_heartbeat_time, last_seen_id) = _poll(
                db_path=str(db_path),
                overlay_url=overlay_url,
                last_seen_id=last_seen_id,
                current_state=current_state,
                previous_snapshot=previous_snapshot,
                now=time.time(),
                last_heartbeat_time=last_heartbeat_time,
                heartbeat_interval=heartbeat_interval,
            )
        except KeyboardInterrupt:
            print("Watcher stopped by user")
            break
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)

        if one_shot:
            break
        time.sleep(poll_interval)


def _poll(
    *,
    db_path: str,
    overlay_url: str,
    last_seen_id: int,
    current_state: Optional[str],
    previous_snapshot: Optional[dict],
    now: float,
    last_heartbeat_time: float,
    heartbeat_interval: float,
) -> tuple[Optional[str], Optional[dict], float, int]:
    """Single poll iteration. Returns (current_state, previous_snapshot, last_heartbeat_time, last_seen_id)."""
    # Get new messages
    try:
        new_msgs = get_new_messages(db_path, after_id=last_seen_id)
    except StateDBError as e:
        print(f"DB error: {e}", file=sys.stderr)
        # Emit unknown state
        if current_state != STATE_UNKNOWN:
            event = build_event("state_change", STATE_UNKNOWN,
                                {"reason": "db_error", "error": str(e)})
            send_event(overlay_url, event)
            current_state = STATE_UNKNOWN
        return current_state, previous_snapshot, last_heartbeat_time, last_seen_id

    if not new_msgs:
        # No new messages — check if session just ended, or expire old state
        now_ts = now

        # Check fresh live_state first — if Hermes is actively writing
        # live_state, don't expire even without new transcript messages.
        live_states = get_live_states(db_path, now=now)
        live_state_used = bool(live_states)

        # If we were in an active state (thinking, tool_running) and no
        # new messages for STATE_TIMEOUT seconds, transition to idle/done
        state_expired = False
        if not live_state_used and current_state in (STATE_THINKING, STATE_TOOL_RUNNING, "listening", "waiting_for_jack"):
            # Check the latest message timestamp to see if it's stale
            try:
                conn2 = sqlite3.connect(db_path)
                cur2 = conn2.execute("SELECT MAX(m.timestamp) FROM messages m WHERE m.role IN ('assistant','tool','user')")
                row2 = cur2.fetchone()
                conn2.close()
                if row2 and row2[0] is not None:
                    last_any_ts = row2[0]
                    if (now_ts - last_any_ts) > DEFAULT_IDLE_THRESHOLD_SECONDS:
                        # The latest message is older than idle threshold → expire
                        state_expired = True
            except (sqlite3.Error, FileNotFoundError, PermissionError):
                pass

        session_ended, ended_sid = has_session_just_ended(
            db_path, previous_snapshot
        )
        latest_snapshot = get_session_snapshot(db_path, checked_at=now)
        if session_ended and current_state != STATE_DONE:
            event = build_event("state_change", STATE_DONE,
                                {"session_id": ended_sid})
            send_event(overlay_url, event)
            current_state = STATE_DONE
            print(f"  → done (session ended)")
        elif state_expired and current_state != STATE_IDLE:
            event = build_event("state_change", STATE_IDLE,
                                {"reason": "timeout"})
            send_event(overlay_url, event)
            current_state = STATE_IDLE
            print(f"  → idle (timeout)")
        elif live_state_used:
            # Fresh live_state exists even without new transcript messages.
            # Aggregate and emit if the state changed.
            best_state = STATE_IDLE
            best_priority = LIVE_STATE_PRIORITY.get(STATE_IDLE, 0)
            for ls in live_states.values():
                pri = LIVE_STATE_PRIORITY.get(ls["state"], 0)
                if pri > best_priority:
                    best_priority = pri
                    best_state = ls["state"]
            if best_state != current_state:
                payload: dict = {"_live_state_source": "live_state"}
                # Include tool_name for tool_running
                if best_state == STATE_TOOL_RUNNING:
                    for ls in live_states.values():
                        if ls.get("tool_name"):
                            payload["tool_name"] = ls["tool_name"]
                            break
                event = build_event("state_change", best_state, payload)
                send_event(overlay_url, event)
                current_state = best_state
                print(f"  → {best_state} [live_state]")

        # Use the latest snapshot for subsequent comparisons
        previous_snapshot = latest_snapshot

        # Send heartbeat if idle and heartbeat interval elapsed
        elapsed_since_heartbeat = now - last_heartbeat_time
        if elapsed_since_heartbeat >= heartbeat_interval:
            if current_state is None or current_state in (STATE_IDLE, STATE_DONE):
                # Check if there are active (non-ended) sessions
                try:
                    conn3 = sqlite3.connect(db_path)
                    cur3 = conn3.execute("SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL")
                    active_count = cur3.fetchone()[0] or 0
                    conn3.close()
                    session_active = active_count > 0
                except (sqlite3.Error, FileNotFoundError, PermissionError):
                    session_active = False
                event = build_event("heartbeat", STATE_IDLE,
                                    {"session_active": session_active})
                send_event(overlay_url, event)
                if current_state == STATE_DONE:
                    current_state = STATE_IDLE
                last_heartbeat_time = now

        _persist(last_seen_id, current_state, previous_snapshot, now, last_heartbeat_time)
        return current_state, previous_snapshot, last_heartbeat_time, last_seen_id

    # We have new messages — include recent messages from previous polls so
    # active sessions aren't forgotten, then fold session-ended detection into
    # that global state decision.
    session_ended, ended_sid = has_session_just_ended(
        db_path, previous_snapshot
    )
    latest_snapshot = get_session_snapshot(db_path, checked_at=now)

    # ── Live-state-first inference ──────────────────────────────────
    # If Hermes core wrote fresh live_state, prefer it over transcript
    # inference. Live_state is written during the actual turn lifecycle,
    # providing real-time visibility into thinking/tool_running.
    live_states = get_live_states(db_path, now=now)
    live_state_used = False

    if live_states:
        # Aggregate live states by priority
        best_state = STATE_IDLE
        best_sid: Optional[str] = None
        best_priority = LIVE_STATE_PRIORITY.get(STATE_IDLE, 0)

        for sid, ls in live_states.items():
            state = ls["state"]
            pri = LIVE_STATE_PRIORITY.get(state, 0)
            if pri > best_priority:
                best_priority = pri
                best_state = state
                best_sid = sid

        active_count = sum(
            1 for ls in live_states.values()
            if LIVE_STATE_PRIORITY.get(ls["state"], 0) > LIVE_STATE_PRIORITY.get(STATE_IDLE, 0)
        )

        inferred = best_state
        meta: dict = {
            "per_session": {sid: ls["state"] for sid, ls in live_states.items()},
            "active_count": active_count,
            "dominant_session_id": best_sid,
            "_live_state_source": "live_state",
        }
        live_state_used = True
    else:
        recent_msgs = get_recent_messages(
            db_path,
            since_timestamp=now - DEFAULT_IDLE_THRESHOLD_SECONDS,
        )
        messages_for_inference = _merge_messages_by_id(recent_msgs, new_msgs)
        inferred, meta = infer_global_state(messages_for_inference, now=now)
        meta["_live_state_source"] = "transcript_fallback"

    if session_ended and inferred in (STATE_IDLE, STATE_DONE, STATE_LISTENING) and current_state != STATE_DONE:
        event = build_event("state_change", STATE_DONE,
                            {"session_id": ended_sid})
        send_event(overlay_url, event)
        current_state = STATE_DONE
        print("  → done (session ended during new message)")

        # Update cursor for new messages even when done was detected
        max_id = max(m["id"] for m in new_msgs if m.get("id"))
        if max_id > last_seen_id:
            last_seen_id = max_id

        previous_snapshot = latest_snapshot
        _persist(last_seen_id, current_state, previous_snapshot, now, last_heartbeat_time)
        return current_state, previous_snapshot, last_heartbeat_time, last_seen_id

    # Map to event
    payload: dict = {}
    payload["active_session_count"] = meta.get("active_count", 0)
    if meta.get("dominant_session_id"):
        payload["dominant_session_id"] = meta["dominant_session_id"]
    if meta.get("per_session"):
        payload["per_session"] = meta["per_session"]
    # Include live-state source for overlay DEBUG display
    if meta.get("_live_state_source"):
        payload["_live_state_source"] = meta["_live_state_source"]

    if inferred == STATE_THINKING:
        if live_state_used:
            # Live-state thinking — skip message_preview (fresher than transcript)
            pass
        else:
            dominant_sid = meta.get("dominant_session_id")
            # Use the dominant session's latest message for preview, not new_msgs[-1]
            newest = new_msgs[-1]
            if dominant_sid and messages_for_inference:
                dominant_msgs = [m for m in messages_for_inference
                                 if m.get("session_id") == dominant_sid and m.get("content")]
                if dominant_msgs:
                    newest = dominant_msgs[-1]
            if newest.get("content"):
                payload["message_preview"] = newest["content"][:120]
    elif inferred == STATE_TOOL_RUNNING:
        if live_state_used:
            # Use live_state tool_name from the dominant session
            dominant_sid = meta.get("dominant_session_id")
            if dominant_sid and dominant_sid in live_states:
                ls = live_states[dominant_sid]
                if ls.get("tool_name"):
                    payload["tool_name"] = ls["tool_name"]
        else:
            newest = new_msgs[-1]
            newest_role = newest.get("role", "")
            if newest_role == "tool":
                payload["tool_name"] = "Tool"
    elif inferred == STATE_DONE:
        payload["auto_transition"] = True

    if inferred != current_state:
        # Pretty-print the per-session states for the log
        per_sess = meta.get("per_session", {})
        sess_info = ", ".join(f"{sid[:8]}={s}" for sid, s in sorted(per_sess.items()))
        event = build_event("state_change", inferred, payload)
        sent = send_event(overlay_url, event)
        if sent:
            print(f"  → {inferred} [{sess_info}]")
        else:
            print(f"  → {inferred} [{sess_info}] (overlay not reachable)")
        current_state = inferred

    # Update cursor
    max_id = max(m["id"] for m in new_msgs if m.get("id"))
    if max_id > last_seen_id:
        last_seen_id = max_id

    # Refresh snapshot for done detection on subsequent polls
    previous_snapshot = get_session_snapshot(db_path, checked_at=now)

    _persist(last_seen_id, current_state, previous_snapshot, now, last_heartbeat_time)
    return current_state, previous_snapshot, last_heartbeat_time, last_seen_id


def _persist(
    last_seen_id: int,
    current_state: Optional[str],
    previous_snapshot: Optional[dict],
    now: float,
    last_heartbeat_time: float,
) -> None:
    """Save watcher state to disk."""
    save_state({
        "last_seen_id": last_seen_id,
        "current_state": current_state,
        "db_snapshot": previous_snapshot,
        "checked_at": now,
        "last_heartbeat_time": last_heartbeat_time,
    })


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Hermes Pet Bridge Watcher — polls state.db, emits events"
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to Hermes state.db (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--overlay-url",
        default=DEFAULT_OVERLAY_URL,
        help=f"Windows overlay event URL (default: {DEFAULT_OVERLAY_URL})",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=DEFAULT_HEARTBEAT_INTERVAL,
        help=f"Heartbeat interval in seconds (default: {DEFAULT_HEARTBEAT_INTERVAL})",
    )
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Poll once and exit (for testing)",
    )
    args = parser.parse_args()

    if not Path(args.db_path).exists():
        print(f"Error: DB not found at {args.db_path}", file=sys.stderr)
        sys.exit(1)

    run_watcher(
        db_path=args.db_path,
        overlay_url=args.overlay_url,
        poll_interval=args.poll_interval,
        heartbeat_interval=args.heartbeat_interval,
        one_shot=args.one_shot,
    )


if __name__ == "__main__":
    main()
