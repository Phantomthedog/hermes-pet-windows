"""Tests for live-state tracking — get_live_states, bridge integration, and fallback."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from state_mapper import (
    LIVE_STATE_FRESHNESS_SECONDS,
    STATE_DONE,
    STATE_IDLE,
    STATE_LISTENING,
    STATE_THINKING,
    STATE_TOOL_RUNNING,
    get_live_states,
    infer_global_state,
    infer_state,
    per_session_states,
)
from bridge_watcher import _poll
from tests.test_event_protocol import FakeEventReceiver


def _make_test_db(
    db_path: str,
    *,
    with_live_state: bool = False,
    live_state: str | None = None,
    live_state_age: float = 0.5,
    tool_name: str | None = None,
    session_id: str = "s1",
    with_message: bool = True,
) -> None:
    """Create a test DB with optional live_state columns and values.

    Args:
        db_path: Path to the SQLite database.
        with_live_state: If True, add live_state columns.
        live_state: Live state value (e.g. 'thinking', 'tool_running').
        live_state_age: How many seconds ago live_state was updated.
        tool_name: Current tool name for tool_running state.
        session_id: Session ID to create.
        with_message: If True, add a message row.
    """
    now = time.time() if live_state is None else (time.time() - live_state_age + live_state_age)
    conn = sqlite3.connect(str(db_path))
    if with_live_state:
        conn.execute(
            """CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                source TEXT,
                started_at REAL,
                ended_at REAL,
                live_state TEXT,
                live_state_updated_at REAL,
                current_tool_name TEXT,
                live_state_detail TEXT
            )"""
        )
    else:
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")

    if with_live_state:
        conn.execute(
            "INSERT INTO sessions (id, source, started_at, live_state, live_state_updated_at, current_tool_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, "cli", time.time(), live_state, time.time() - live_state_age, tool_name),
        )
    else:
        conn.execute(
            "INSERT INTO sessions (id, source, started_at) VALUES (?, ?, ?)",
            (session_id, "cli", time.time()),
        )

    if with_message:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, ?, 'assistant', 'Test', ?)",
            (session_id, time.time()),
        )
    conn.commit()
    conn.close()


def _make_multi_session_db(
    db_path: str,
    sessions_data: list[dict],
) -> None:
    """Create a DB with multiple sessions, each with live_state data.

    sessions_data: list of dicts with keys:
        session_id, live_state, live_state_age, tool_name, with_message
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            started_at REAL,
            ended_at REAL,
            live_state TEXT,
            live_state_updated_at REAL,
            current_tool_name TEXT,
            live_state_detail TEXT
        )"""
    )
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")

    now = time.time()
    for i, sd in enumerate(sessions_data):
        sid = sd.get("session_id", f"s{i}")
        state = sd.get("live_state")
        age = sd.get("live_state_age", 1)
        tool = sd.get("tool_name")
        updated_at = now - age
        conn.execute(
            "INSERT INTO sessions (id, source, started_at, live_state, live_state_updated_at, current_tool_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (sid, "cli", now - 100, state, updated_at, tool),
        )
        if sd.get("with_message", True):
            conn.execute(
                "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (?, ?, 'assistant', 'Test', ?)",
                (i + 1, sid, now - 10),
            )
    conn.commit()
    conn.close()


# ── get_live_states unit tests ─────────────────────────────────


class TestGetLiveStates:
    """Test the get_live_states function."""

    def test_no_live_state_columns_returns_empty(self, tmp_path):
        """DB without live_state columns → empty dict (backward compat)."""
        db_path = tmp_path / "old.db"
        _make_test_db(str(db_path), with_live_state=False)
        assert get_live_states(str(db_path)) == {}

    def test_no_live_state_written_returns_empty(self, tmp_path):
        """DB with columns but NULL live_state → empty dict."""
        db_path = tmp_path / "null.db"
        _make_test_db(str(db_path), with_live_state=True, live_state=None)
        assert get_live_states(str(db_path)) == {}

    def test_fresh_live_state_returns_state(self, tmp_path):
        """Fresh live_state='thinking' → returns session with state and age."""
        db_path = tmp_path / "fresh.db"
        _make_test_db(str(db_path), with_live_state=True, live_state="thinking", live_state_age=0.5)
        result = get_live_states(str(db_path))
        assert "s1" in result
        assert result["s1"]["state"] == "thinking"
        assert result["s1"]["age"] < 1.0  # was set 0.5s ago

    def test_stale_live_state_returns_empty(self, tmp_path):
        """live_state older than LIVE_STATE_FRESHNESS_SECONDS → empty dict."""
        db_path = tmp_path / "stale.db"
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="thinking",
            live_state_age=LIVE_STATE_FRESHNESS_SECONDS + 5,  # 35s old
        )
        result = get_live_states(str(db_path))
        assert result == {}

    def test_tool_name_preserved(self, tmp_path):
        """current_tool_name is returned in live_state result."""
        db_path = tmp_path / "tool.db"
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="tool_running",
            live_state_age=0.5,
            tool_name="search_files",
        )
        result = get_live_states(str(db_path))
        assert result["s1"]["state"] == "tool_running"
        assert result["s1"]["tool_name"] == "search_files"

    def test_multiple_sessions(self, tmp_path):
        """Multiple sessions with different live states all returned."""
        db_path = tmp_path / "multi.db"
        _make_multi_session_db(str(db_path), [
            {"session_id": "s1", "live_state": "thinking", "live_state_age": 1},
            {"session_id": "s2", "live_state": "tool_running", "live_state_age": 2, "tool_name": "terminal"},
        ])
        result = get_live_states(str(db_path))
        assert len(result) == 2
        assert result["s1"]["state"] == "thinking"
        assert result["s2"]["state"] == "tool_running"
        assert result["s2"]["tool_name"] == "terminal"

    def test_missing_db_returns_empty(self):
        """Non-existent DB path → empty dict, never raises."""
        result = get_live_states("/tmp/nonexistent_state_db_98765.db")
        assert result == {}


# ── Bridge integration tests ──────────────────────────────────


class TestBridgeWithLiveState:
    """Test that bridge_watcher._poll correctly uses live-state."""

    def test_live_state_thinking_used_over_transcript(self, tmp_path):
        """Fresh live_state='thinking' → global state is thinking."""
        db_path = tmp_path / "live_thinking.db"
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="thinking",
            live_state_age=0.5,
            with_message=True,
        )
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state=None,
                previous_snapshot=None,
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            assert current_state == "thinking"
            assert len(receiver.received_events) >= 1
            evt = receiver.received_events[0]
            assert evt["state"] == "thinking"
            assert evt["payload"].get("_live_state_source") == "live_state"
        finally:
            receiver.stop()

    def test_live_state_tool_running_with_name(self, tmp_path):
        """Fresh live_state='tool_running' with tool_name → tool_name in payload."""
        db_path = tmp_path / "live_tool.db"
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="tool_running",
            live_state_age=0.5,
            tool_name="search_files",
            with_message=True,
        )
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state=None,
                previous_snapshot=None,
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            assert current_state == "tool_running"
            assert receiver.received_events[-1]["payload"].get("tool_name") == "search_files"
        finally:
            receiver.stop()

    def test_no_live_state_falls_back_to_transcript(self, tmp_path):
        """DB without live_state columns → transcript inference works."""
        db_path = tmp_path / "nofallback.db"
        _make_test_db(
            str(db_path),
            with_live_state=False,
            with_message=True,
        )
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state=None,
                previous_snapshot=None,
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            # With an assistant message, transcript inference → thinking
            assert current_state == "thinking"
            assert receiver.received_events[-1]["payload"].get("_live_state_source") == "transcript_fallback"
        finally:
            receiver.stop()

    def test_stale_live_state_falls_back_to_transcript(self, tmp_path):
        """Stale live_state (beyond freshness window) → transcript inference used."""
        db_path = tmp_path / "stale_fallback.db"
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="thinking",
            live_state_age=LIVE_STATE_FRESHNESS_SECONDS + 10,  # 40s old → stale
            with_message=True,
        )
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state=None,
                previous_snapshot=None,
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            # Stale live_state → transcript fallback → thinking from assistant message
            assert current_state == "thinking"
            assert receiver.received_events[-1]["payload"].get("_live_state_source") == "transcript_fallback"
        finally:
            receiver.stop()

    def test_multiple_sessions_aggregation(self, tmp_path):
        """Multiple sessions with different live states → highest priority wins."""
        db_path = tmp_path / "multi_agg.db"
        _make_multi_session_db(str(db_path), [
            {"session_id": "s1", "live_state": "thinking", "live_state_age": 1},
            {"session_id": "s2", "live_state": "done", "live_state_age": 2},
        ])
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state=None,
                previous_snapshot=None,
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            # thinking (prio 80) > done (prio 50)
            assert current_state == "thinking"
        finally:
            receiver.stop()

    def test_multiple_sessions_tool_running_wins(self, tmp_path):
        """Tool_running dominates over listening."""
        db_path = tmp_path / "multi_tool_listen.db"
        _make_multi_session_db(str(db_path), [
            {"session_id": "s1", "live_state": "tool_running", "live_state_age": 1, "tool_name": "terminal"},
            {"session_id": "s2", "live_state": "listening", "live_state_age": 1},
        ])
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state=None,
                previous_snapshot=None,
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            # tool_running (prio 90) > listening (prio 60)
            assert current_state == "tool_running"
            assert receiver.received_events[-1]["payload"].get("tool_name") == "terminal"
        finally:
            receiver.stop()

    def test_no_new_messages_but_fresh_live_state(self, tmp_path):
        """No new messages but live_state fresh → state doesn't expire."""
        db_path = tmp_path / "no_msg_live.db"
        # Create DB with no messages but fresh live_state
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="thinking",
            live_state_age=1,
            with_message=False,  # no messages
        )
        # Set current_state to a previous active state
        now = time.time()
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state="thinking",
                previous_snapshot={"ended_sessions": [], "checked_at": now - 2},
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )
            # Should NOT expire to idle because live_state is fresh
            assert current_state == "thinking"
        finally:
            receiver.stop()

    def test_live_state_age_limited_by_freshness(self, tmp_path):
        """Live_state at boundary of freshness window → still visible."""
        db_path = tmp_path / "boundary.db"
        _make_test_db(
            str(db_path),
            with_live_state=True,
            live_state="thinking",
            live_state_age=LIVE_STATE_FRESHNESS_SECONDS - 1,  # 29s — just within window
            with_message=True,
        )
        result = get_live_states(str(db_path))
        assert len(result) == 1
        assert result["s1"]["state"] == "thinking"
        assert result["s1"]["age"] < LIVE_STATE_FRESHNESS_SECONDS
