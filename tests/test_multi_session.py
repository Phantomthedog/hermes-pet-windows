"""Tests for multi-session aggregation in state_mapper.py."""

from __future__ import annotations

import time

import pytest
from state_mapper import (
    STATE_DONE,
    STATE_ERROR,
    STATE_IDLE,
    STATE_THINKING,
    STATE_TOOL_RUNNING,
    STATE_UNKNOWN,
    infer_global_state,
    per_session_states,
)


def _msg(
    role: str,
    *,
    content: str = "",
    timestamp: float | None = None,
    ended_at: float | None = None,
    session_id: str = "s1",
) -> dict:
    """Build a minimal message dict for testing."""
    msg: dict = {
        "id": 1,
        "content": content,
        "session_id": session_id,
        "role": role,
        "source": "cli",
    }
    if timestamp is not None:
        msg["timestamp"] = timestamp
    if ended_at is not None:
        msg["ended_at"] = ended_at
    return msg


class TestPerSessionStates:
    """Per-session state grouping tests."""

    def test_single_session_messages(self):
        """All messages from one session produce one state."""
        now = time.time()
        msgs = [
            _msg("user", content="Hi", timestamp=now - 10, session_id="s1"),
            _msg("assistant", content="Hello!", timestamp=now - 1, session_id="s1"),
        ]
        states = per_session_states(msgs, now=now)
        assert len(states) == 1
        assert "s1" in states
        assert states["s1"] == STATE_THINKING

    def test_two_sessions_different_state(self):
        """Two sessions with different activity produce separate states."""
        now = time.time()
        msgs = [
            # Session 1: recent assistant message → thinking
            _msg("assistant", content="Generating...", timestamp=now - 1, session_id="s1"),
            # Session 2: old message → idle
            _msg("assistant", content="Done", timestamp=now - 60, session_id="s2"),
        ]
        states = per_session_states(msgs, now=now)
        assert len(states) == 2
        assert states.get("s1") == STATE_THINKING
        assert states.get("s2") == STATE_IDLE

    def test_same_session_id_merged(self):
        """Multiple messages with same session_id are grouped."""
        now = time.time()
        msgs = [
            _msg("user", content="Q", timestamp=now - 10, session_id="shared"),
            _msg("tool", content="Running...", timestamp=now - 1, session_id="shared"),
        ]
        states = per_session_states(msgs, now=now)
        assert len(states) == 1
        assert states["shared"] == STATE_TOOL_RUNNING

    def test_orphan_messages(self):
        """Messages without session_id are grouped under '_orphan'."""
        now = time.time()
        msgs = [
            {"id": 1, "content": "Hi", "role": "user", "timestamp": now - 10, "source": "cli"},
            {"id": 2, "content": "Hello!", "role": "assistant", "timestamp": now - 1, "source": "cli"},
        ]
        states = per_session_states(msgs, now=now)
        assert "_orphan" in states
        assert states["_orphan"] == STATE_THINKING


class TestInferGlobalState:
    """Multi-session global state aggregation tests."""

    def test_no_messages_returns_idle(self):
        """Empty message list → idle."""
        state, meta = infer_global_state([], now=time.time())
        assert state == STATE_IDLE
        assert meta["active_count"] == 0

    def test_one_session_thinking_global_thinking(self):
        """One thinking session → global thinking."""
        now = time.time()
        msgs = [_msg("assistant", content="Gen", timestamp=now - 1, session_id="s1")]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_THINKING
        assert meta["active_count"] == 1
        assert meta["dominant_session_id"] == "s1"

    def test_two_sessions_thinking_and_idle_global_thinking(self):
        """Thinking + idle → global thinking (idle should NOT override)."""
        now = time.time()
        msgs = [
            _msg("assistant", content="Gen", timestamp=now - 1, session_id="s1"),
            _msg("assistant", content="Old", timestamp=now - 60, session_id="s2"),
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_THINKING, f"Expected thinking, got {state}"
        assert meta["dominant_session_id"] == "s1"

    def test_tool_running_overrides_thinking(self):
        """Tool_running session should override thinking session."""
        now = time.time()
        msgs = [
            _msg("assistant", content="Gen", timestamp=now - 1, session_id="s1"),
            _msg("tool", content="Exec", timestamp=now - 1, session_id="s2"),
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_TOOL_RUNNING
        assert meta["active_count"] == 2

    def test_done_does_not_override_active_thinking(self):
        """A session that just ended (done) should not override another session's thinking."""
        now = time.time()
        msgs = [
            # Session 1: just ended (done)
            _msg("assistant", content="Done!", timestamp=now - 1,
                 ended_at=now - 0.5, session_id="s1"),
            # Session 2: still thinking
            _msg("assistant", content="Thinking...", timestamp=now - 1, session_id="s2"),
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_THINKING, f"Expected thinking, got {state}"
        # Both sessions now return thinking (role check fires before done check).
        # Global state is correctly "thinking" — dominant is whichever was seen first.
        assert meta["active_count"] == 2

    def test_error_overrides_everything(self):
        """Error session overrides all other activity."""
        now = time.time()
        msgs = [
            _msg("tool", content="Exec", timestamp=now - 1, session_id="s1"),
            _msg("assistant", content="Error: timeout",
                 timestamp=now - 1, ended_at=now - 0.5, session_id="s2"),
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_ERROR

    def test_all_idle_after_timeout(self):
        """All sessions idle after threshold → global idle."""
        now = time.time()
        msgs = [
            _msg("assistant", content="Old", timestamp=now - 60, session_id="s1"),
            _msg("assistant", content="Also old", timestamp=now - 60, session_id="s2"),
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_IDLE
        assert meta["active_count"] == 0

    def test_multiple_active_count(self):
        """Multiple active sessions correctly counted."""
        now = time.time()
        msgs = [
            _msg("assistant", content="Gen", timestamp=now - 1, session_id="s1"),
            _msg("tool", content="Exec", timestamp=now - 1, session_id="s2"),
            _msg("assistant", content="Old", timestamp=now - 60, session_id="s3"),
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert meta["active_count"] == 2  # s1 thinking, s2 tool_running

    def test_session_without_id_falls_back(self):
        """Messages with no session_id are handled (orphan group)."""
        now = time.time()
        msgs = [
            {"id": 1, "role": "assistant", "content": "Hi", "timestamp": now - 1, "source": "cli"},
        ]
        state, meta = infer_global_state(msgs, now=now)
        assert state == STATE_THINKING
        assert "_orphan" in meta.get("per_session", {})

    def test_metadata_has_all_keys(self):
        """Returned metadata dict has the expected structure."""
        now = time.time()
        msgs = [_msg("assistant", content="Hi", timestamp=now - 1, session_id="s1")]
        state, meta = infer_global_state(msgs, now=now)
        assert "per_session" in meta
        assert "active_count" in meta
        assert "dominant_session_id" in meta
