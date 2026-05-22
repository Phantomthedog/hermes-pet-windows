"""Tests for state_mapper.py — DB state → protocol state mapping."""

from __future__ import annotations

import time
import pytest
from state_mapper import (
    STATE_DONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_THINKING,
    STATE_TOOL_RUNNING,
    STATE_UNKNOWN,
    infer_state,
)


def _msg(
    role: str,
    *,
    content: str = "",
    timestamp: float | None = None,
    ended_at: float | None = None,
) -> dict:
    """Build a minimal message dict for testing."""
    msg: dict = {
        "id": 1,
        "content": content,
        "session_id": "test_session",
        "role": role,
        "source": "cli",
    }
    if timestamp is not None:
        msg["timestamp"] = timestamp
    if ended_at is not None:
        msg["ended_at"] = ended_at
    return msg


class TestInferState:
    """Core state inference logic."""

    def test_no_messages_returns_idle(self):
        """Empty message list → idle."""
        assert infer_state([], now=time.time()) == STATE_IDLE

    def test_old_message_returns_idle(self):
        """Message older than idle_threshold → idle."""
        now = time.time()
        old = now - 60  # 60 seconds ago
        msgs = [_msg("assistant", content="Done", timestamp=old)]
        assert infer_state(msgs, idle_threshold=30, now=now) == STATE_IDLE

    def test_recent_assistant_message_returns_thinking(self):
        """Recent assistant message → thinking."""
        now = time.time()
        recent = now - 1  # 1 second ago
        msgs = [_msg("assistant", content="Generating...", timestamp=recent)]
        assert infer_state(msgs, now=now) == STATE_THINKING

    def test_recent_tool_message_returns_tool_running(self):
        """Recent tool message → tool_running."""
        now = time.time()
        recent = now - 1
        msgs = [_msg("tool", content="Executing command...", timestamp=recent)]
        assert infer_state(msgs, now=now) == STATE_TOOL_RUNNING

    def test_assistant_message_too_old_returns_idle(self):
        """Assistant message just over thinking_fresh → idle."""
        now = time.time()
        old = now - 10  # 10 seconds, over 5s threshold
        msgs = [_msg("assistant", content="Done", timestamp=old)]
        assert infer_state(msgs, thinking_fresh=5, now=now) == STATE_IDLE

    def test_ended_session_returns_done(self):
        """Session with ended_at recently set → done (when message role doesn't match active states)."""
        now = time.time()
        recent = now - 2  # within done window (3s)
        msgs = [{"id": 1, "content": "Final answer", "session_id": "s1",
                 "role": "", "timestamp": recent, "ended_at": now - 0.3,
                 "source": "cli"}]
        assert infer_state(msgs, now=now) == STATE_DONE

    def test_ended_session_with_error_content(self):
        """Session ending with error keywords → error (when message role doesn't match active states)."""
        now = time.time()
        msgs = [{"id": 1, "content": "Error: Connection failed", "session_id": "s1",
                 "role": "", "timestamp": now - 2,
                 "ended_at": now - 0.3, "source": "cli"}]
        assert infer_state(msgs, now=now) == STATE_ERROR

    def test_recent_user_message_returns_idle(self):
        """User message within idle threshold → listening, beyond → idle."""
        now = time.time()
        recent = now - 15  # beyond idle_threshold (10)
        msgs = [_msg("user", content="Hello", timestamp=recent)]
        assert infer_state(msgs, idle_threshold=10, now=now) == STATE_IDLE

        # User message within idle_threshold shows listening
        msgs2 = [_msg("user", content="Hi", timestamp=now - 3)]
        assert infer_state(msgs2, idle_threshold=10, now=now) == STATE_LISTENING

    def test_missing_timestamp_returns_idle(self):
        """Message with no timestamp → idle."""
        msgs = [_msg("assistant", content="Hello", timestamp=None)]
        assert infer_state(msgs, now=time.time()) == STATE_IDLE

    def test_messages_outside_threshold_return_idle(self):
        """Messages older than idle_threshold → idle regardless of role."""
        now = time.time()
        old = now - 300  # 5 minutes ago
        for role in ("assistant", "tool", "user"):
            msgs = [_msg(role, content="Old message", timestamp=old)]
            assert infer_state(msgs, idle_threshold=30, now=now) == STATE_IDLE

    def test_recent_tool_message_freshness(self):
        """Tool message exactly at tool_fresh boundary."""
        now = time.time()
        boundary = now - 5  # exactly 5 seconds
        msgs = [_msg("tool", content="Processing", timestamp=boundary)]
        assert infer_state(msgs, tool_fresh=5, now=now) == STATE_TOOL_RUNNING
        # Just over boundary
        slightly_older = now - 5.1
        msgs2 = [_msg("tool", content="Processing", timestamp=slightly_older)]
        assert infer_state(msgs2, tool_fresh=5, now=now) == STATE_IDLE


class TestMultipleMessages:
    """State inference with multiple messages."""

    def test_latest_message_wins(self):
        """The most recent message determines state."""
        now = time.time()
        msgs = [
            _msg("assistant", content="Old response", timestamp=now - 60),
            _msg("user", content="Follow up", timestamp=now - 30),
            _msg("tool", content="Recent tool", timestamp=now - 1),
        ]
        assert infer_state(msgs, now=now) == STATE_TOOL_RUNNING

    def test_mixed_roles_thinking_wins_when_latest(self):
        """Latest assistant message → thinking."""
        now = time.time()
        msgs = [
            _msg("tool", content="Tool result", timestamp=now - 10),
            _msg("assistant", content="Final answer", timestamp=now - 1),
        ]
        assert infer_state(msgs, now=now) == STATE_THINKING


class TestEndedSessionDetection:
    """Session ended detection from previous snapshot."""

    def test_no_previous_snapshot(self):
        """Without previous snapshot, no session-ended signal."""
        from state_mapper import has_session_just_ended
        result, sid = has_session_just_ended("/tmp/nonexistent.db", None)
        assert result is False
        assert sid is None


def test_get_session_snapshot_returns_json_safe_ended_session_list(tmp_path):
    """Session snapshots use lists, not sets, so bridge state can be JSON persisted."""
    import sqlite3
    from state_mapper import get_session_snapshot

    db_path = tmp_path / "snapshot.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
    conn.execute("INSERT INTO sessions (id, source, started_at, ended_at) VALUES ('s1', 'cli', 1.0, 2.0)")
    conn.execute("INSERT INTO sessions (id, source, started_at, ended_at) VALUES ('s2', 'cli', 1.0, NULL)")
    conn.commit()
    conn.close()

    snapshot = get_session_snapshot(str(db_path), checked_at=123.0)

    assert snapshot == {"ended_sessions": ["s1"], "checked_at": 123.0}
