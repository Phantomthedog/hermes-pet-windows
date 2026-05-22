"""Hermes state.db → protocol state mapping.

Reads the SQLite state.db and maps database state to the event protocol state.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Default idle threshold: if no messages in this many seconds, consider idle
DEFAULT_IDLE_THRESHOLD_SECONDS = 10

# How long a new assistant message is considered "in progress" (thinking)
THINKING_FRESH_SECONDS = 3

# How long a tool message is considered "running"
TOOL_FRESH_SECONDS = 3

# How long after a user message before we consider the agent "listening"
LISTENING_FRESH_SECONDS = 2

# How long a live_state value is considered "fresh" (not stale)
LIVE_STATE_FRESHNESS_SECONDS = 30

# Priority for live-state aggregation (same ordering as _STATE_PRIORITY)
LIVE_STATE_PRIORITY = {
    "error": 100,
    "tool_running": 90,
    "thinking": 80,
    "waiting_for_jack": 70,
    "listening": 60,
    "done": 50,
    "idle": 10,
    "unknown": 0,
    # For safety, if the DB has raw state that matches none of the above
}

# States we can reliably detect
STATE_IDLE = "idle"
STATE_LISTENING = "listening"
STATE_THINKING = "thinking"
STATE_TOOL_RUNNING = "tool_running"
STATE_DONE = "done"
STATE_ERROR = "error"
STATE_UNKNOWN = "unknown"


class StateDBError(Exception):
    """Raised when state.db cannot be read or queried."""
    pass


@dataclass
class SessionSnapshot:
    """Snapshot of the Hermes session state."""
    has_active_session: bool
    latest_state: str  # The inferred Hermes state
    latest_message_id: int
    latest_message_role: Optional[str]
    latest_message_content: Optional[str]
    latest_timestamp: Optional[float]
    session_id: Optional[str]
    last_ended_session_id: Optional[str]  # Session that just ended



def get_latest_message_id(db_path: str | Path) -> Optional[int]:
    """Get the max message ID from state.db.

    Returns None if the DB is empty or unreadable.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute("SELECT MAX(id) FROM messages")
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else None
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError, PermissionError):
        return None


def get_new_messages(
    db_path: str | Path,
    after_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Get messages newer than after_id, joined with session info.

    Returns list of dicts with keys: id, content, session_id, role, timestamp,
    ended_at, source.
    """
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                SELECT m.id, m.content, m.session_id, m.role, m.timestamp,
                       s.ended_at, s.source
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                WHERE m.id > ?
                  AND m.role IN ('assistant', 'tool', 'user')
                ORDER BY m.id ASC
                LIMIT ?
                """,
                (after_id, limit),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError, PermissionError) as e:
        raise StateDBError(f"Failed to query messages: {e}") from e


def get_recent_messages(
    db_path: str | Path,
    since_timestamp: float,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Get recent assistant/tool/user messages across all sessions for global state inference."""
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                SELECT m.id, m.content, m.session_id, m.role, m.timestamp,
                       s.ended_at, s.source
                FROM messages m
                JOIN sessions s ON m.session_id = s.id
                WHERE m.timestamp >= ?
                  AND m.role IN ('assistant', 'tool', 'user')
                ORDER BY m.id ASC
                LIMIT ?
                """,
                (since_timestamp, limit),
            )
            return [dict(row) for row in cur.fetchall()]
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError, PermissionError) as e:
        raise StateDBError(f"Failed to query recent messages: {e}") from e


def infer_state(
    messages: list[dict[str, Any]],
    *,
    idle_threshold: float = DEFAULT_IDLE_THRESHOLD_SECONDS,
    thinking_fresh: float = THINKING_FRESH_SECONDS,
    tool_fresh: float = TOOL_FRESH_SECONDS,
    now: Optional[float] = None,
) -> str:
    """Infer Hermes agent state from a list of recent messages.

    Args:
        messages: Sorted list of message dicts (oldest first).
        idle_threshold: Seconds without activity → idle.
        thinking_fresh: Seconds within which an assistant message is "thinking".
        tool_fresh: Seconds within which a tool message is "tool_running".
        now: Current timestamp (for testing).

    Returns:
        One of the HERMES_STATES values.
    """
    if now is None:
        now = time.time()

    if not messages:
        # No messages at all — first start or no session
        return STATE_IDLE

    newest = messages[-1]
    newest_role = newest.get("role", "")
    newest_ts = newest.get("timestamp")
    ended_at = newest.get("ended_at")
    content = newest.get("content", "")

    # If timestamp is missing, fall back to idle
    if newest_ts is None:
        return STATE_IDLE

    elapsed = now - newest_ts

    # User just sent a message — agent is processing, show listening
    # Check this before the idle threshold so the pet reacts immediately
    # when the user drops a prompt, without waiting for model to write back
    if newest_role == "user" and elapsed <= idle_threshold:
        return STATE_LISTENING

    # Stale messages fall to idle first
    if elapsed > idle_threshold:
        return STATE_IDLE

    # Error check — ended sessions with error keywords always override
    if ended_at is not None and elapsed <= 3:
        if content and any(word in (content.lower() or "") for word in
                           ["error", "exception", "failed", "traceback"]):
            return STATE_ERROR

    # Active session, recent messages — check role first so intermediate
    # states (thinking, tool_running) appear before the session-end done fires
    if newest_role == "assistant" and elapsed <= thinking_fresh:
        return STATE_THINKING

    if newest_role == "tool" and elapsed <= tool_fresh:
        return STATE_TOOL_RUNNING

    # User just sent a message — agent is processing their request
    if newest_role == "user" and elapsed <= LISTENING_FRESH_SECONDS:
        return STATE_LISTENING

    # Check for plain completed session (no error) — done AFTER role checks
    # so intermediate states are shown first; has_session_just_ended() in
    # the bridge's no-new-messages branch will fire done on the next poll
    if ended_at is not None and elapsed <= 3:
        return STATE_DONE

    # Session exists but no clear state → active idle
    return STATE_IDLE


# ── Multi-session aggregation ────────────────────

# Priority order: higher number = more important
_STATE_PRIORITY = {
    "error": 100,
    "tool_running": 90,
    "thinking": 80,
    "waiting_for_jack": 70,
    "listening": 60,
    "done": 50,
    "idle": 10,
    "unknown": 0,
}


def per_session_states(
    messages: list[dict[str, Any]],
    *,
    idle_threshold: float = DEFAULT_IDLE_THRESHOLD_SECONDS,
    thinking_fresh: float = THINKING_FRESH_SECONDS,
    tool_fresh: float = TOOL_FRESH_SECONDS,
    now: Optional[float] = None,
) -> dict[str, str]:
    """Group messages by session_id and infer per-session states.

    Returns a dict mapping session_id → inferred state string.
    Messages without a session_id are grouped under "_orphan".
    """
    if now is None:
        now = time.time()

    # Group by session_id
    by_session: dict[str, list[dict]] = {}
    for msg in messages:
        sid = msg.get("session_id") or "_orphan"
        if sid not in by_session:
            by_session[sid] = []
        by_session[sid].append(msg)

    result: dict[str, str] = {}
    for sid, session_msgs in by_session.items():
        result[sid] = infer_state(
            session_msgs,
            idle_threshold=idle_threshold,
            thinking_fresh=thinking_fresh,
            tool_fresh=tool_fresh,
            now=now,
        )
    return result


def infer_global_state(
    messages: list[dict[str, Any]],
    *,
    idle_threshold: float = DEFAULT_IDLE_THRESHOLD_SECONDS,
    thinking_fresh: float = THINKING_FRESH_SECONDS,
    tool_fresh: float = TOOL_FRESH_SECONDS,
    now: Optional[float] = None,
) -> tuple[str, dict[str, Any]]:
    """Group messages by session, infer per-session states, then aggregate.

    Returns (global_state, metadata) where metadata includes:
    - per_session: dict of session_id → state
    - active_count: number of non-idle sessions
    - dominant_session_id: session driving the global state (or None)
    """
    pss = per_session_states(
        messages,
        idle_threshold=idle_threshold,
        thinking_fresh=thinking_fresh,
        tool_fresh=tool_fresh,
        now=now,
    )

    if not pss:
        return STATE_IDLE, {"per_session": {}, "active_count": 0, "dominant_session_id": None}

    # Find the highest-priority state
    best_state = STATE_IDLE
    best_sid: Optional[str] = None
    best_priority = _STATE_PRIORITY.get(STATE_IDLE, 0)

    for sid, state in pss.items():
        pri = _STATE_PRIORITY.get(state, 0)
        if pri > best_priority:
            best_priority = pri
            best_state = state
            best_sid = sid

    active_count = sum(
        1 for s in pss.values()
        if _STATE_PRIORITY.get(s, 0) > _STATE_PRIORITY.get(STATE_IDLE, 0)
    )

    return best_state, {
        "per_session": pss,
        "active_count": active_count,
        "dominant_session_id": best_sid,
    }


def get_live_states(
    db_path: str | Path,
    *,
    now: Optional[float] = None,
) -> dict[str, dict]:
    """Read fresh live_state values from the sessions table.

    Only returns sessions where live_state is not None and
    live_state_updated_at is within LIVE_STATE_FRESHNESS_SECONDS.

    Returns a dict mapping session_id → {
        "state": str,
        "tool_name": Optional[str],
        "detail": Optional[str],
        "age": float (seconds),
    }

    Returns empty dict on error or if the DB lacks live_state columns
    (older Hermes version). Never raises.
    """
    if now is None:
        now = time.time()
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cutoff = now - LIVE_STATE_FRESHNESS_SECONDS
            cur = conn.execute(
                """SELECT id, live_state, live_state_updated_at,
                          current_tool_name, live_state_detail
                   FROM sessions
                   WHERE live_state IS NOT NULL
                     AND live_state_updated_at >= ?""",
                (cutoff,),
            )
            rows = cur.fetchall()
            if not rows:
                return {}
            result: dict[str, dict] = {}
            for row in rows:
                sid = row["id"]
                updated_at = row["live_state_updated_at"]
                age = now - updated_at
                result[sid] = {
                    "state": row["live_state"],
                    "tool_name": row["current_tool_name"] if row["current_tool_name"] is not None else None,
                    "detail": row["live_state_detail"] if row["live_state_detail"] is not None else None,
                    "age": age,
                }
            return result
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError, PermissionError):
        return {}  # Older DB without columns or DB issues → silent fallback


def get_session_snapshot(
    db_path: str | Path,
    *,
    checked_at: Optional[float] = None,
) -> dict[str, Any]:
    """Return a JSON-safe snapshot of ended sessions for later done detection."""
    if checked_at is None:
        checked_at = time.time()

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(
                """
                SELECT id FROM sessions
                WHERE ended_at IS NOT NULL
                ORDER BY ended_at ASC, id ASC
                """
            )
            ended_sessions = [row["id"] for row in cur.fetchall()]
            return {"ended_sessions": ended_sessions, "checked_at": checked_at}
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError, PermissionError) as e:
        raise StateDBError(f"Failed to query session snapshot: {e}") from e


def has_session_just_ended(
    db_path: str | Path,
    previous_snapshot: Optional[dict[str, Any]],
) -> tuple[bool, Optional[str]]:
    """Check if a session ended since the last poll.

    Returns (True, session_id) if a session just ended, (False, None) otherwise.
    """
    if previous_snapshot is None:
        # First poll — record current ended_at values for later comparison
        return False, None

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Sessions that ended since last check
            prev_ended = set(previous_snapshot.get("ended_sessions", []))
            cur = conn.execute(
                """
                SELECT id FROM sessions
                WHERE ended_at IS NOT NULL
                  AND ended_at > ?
                ORDER BY ended_at DESC
                LIMIT 5
                """,
                (previous_snapshot.get("checked_at", 0),),
            )
            new_ended = [row["id"] for row in cur.fetchall()]
            newly_ended = [s for s in new_ended if s not in prev_ended]
            if newly_ended:
                return True, newly_ended[0]
            return False, None
        finally:
            conn.close()
    except (sqlite3.Error, FileNotFoundError, PermissionError):
        return False, None
