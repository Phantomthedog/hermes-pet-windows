"""Tests for bridge_watcher.py — integration tests using FakeEventReceiver."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from event_schema import build_event
from bridge_watcher import _poll
from tests.test_event_protocol import FakeEventReceiver


def _make_test_db(db_path: str, *, with_message: bool = True) -> None:
    """Helper: create a sqlite DB with sessions and messages tables."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
    conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
    conn.execute("INSERT INTO sessions (id, source, started_at) VALUES ('s1', 'cli', 1000.0)")
    if with_message:
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, 's1', 'assistant', 'Generating response', ?)",
            (time.time(),)
        )
    conn.commit()
    conn.close()


class TestBridgeWatcherPoll:
    """Test the _poll function's behavior."""

    def test_poll_no_new_messages_returns_none(self, tmp_path):
        """When no messages and no overlay, poll returns None current_state."""
        db_path = tmp_path / "empty.db"
        _make_test_db(str(db_path), with_message=False)

        now = time.time()
        current_state, prev_snapshot, last_hb, last_id = _poll(
            db_path=str(db_path),
            overlay_url="http://127.0.0.1:0/event/",
            last_seen_id=0,
            current_state=None,
            previous_snapshot=None,
            now=now,
            last_heartbeat_time=now,
            heartbeat_interval=5.0,
        )
        # No overlay running so events fail silently — state should remain None
        assert current_state is None

    def test_poll_with_new_messages_detects_thinking(self, tmp_path):
        """When messages exist, infer_state determines thinking."""
        db_path = tmp_path / "test.db"
        _make_test_db(str(db_path), with_message=True)

        # Start a receiver to catch the event
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
            assert evt["event_type"] == "state_change"
            assert evt["state"] == "thinking"
        finally:
            receiver.stop()

    def test_poll_missing_db_emits_unknown(self):
        """When DB is missing, poll emits unknown."""
        now = time.time()
        current_state, prev_snapshot, last_hb, last_id = _poll(
            db_path="/tmp/nonexistent_state_db_12345.db",
            overlay_url="http://127.0.0.1:0/event/",
            last_seen_id=0,
            current_state=None,
            previous_snapshot=None,
            now=now,
            last_heartbeat_time=now,
            heartbeat_interval=5.0,
        )
        assert current_state == "unknown"

    def test_poll_sends_heartbeat_when_idle(self, tmp_path):
        """When idle and heartbeat interval elapsed, poll sends heartbeat."""
        db_path = tmp_path / "empty_hb.db"
        _make_test_db(str(db_path), with_message=False)

        receiver = FakeEventReceiver()
        receiver.start()
        try:
            now = time.time()
            # Set last_heartbeat_time far in the past to trigger heartbeat
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=0,
                current_state="idle",
                previous_snapshot={"some": "data"},
                now=now,
                last_heartbeat_time=now - 10,
                heartbeat_interval=5.0,
            )

            assert current_state == "idle"
            # Should have received a heartbeat
            heartbeats = [e for e in receiver.received_events if e["event_type"] == "heartbeat"]
            assert len(heartbeats) >= 1
        finally:
            receiver.stop()

    def test_poll_aggregates_recent_messages_from_previous_poll(self, tmp_path):
        """A recent active session remains visible even when only another session has a new row."""
        import sqlite3

        db_path = tmp_path / "multi_session.db"
        now = 1000.0
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        conn.execute("INSERT INTO sessions (id, source, started_at) VALUES ('s1', 'cli', 900.0)")
        conn.execute("INSERT INTO sessions (id, source, started_at) VALUES ('s2', 'cli', 950.0)")
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, 's1', 'assistant', 'Still working', ?)",
            (now - 2,),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (2, 's2', 'user', 'New prompt', ?)",
            (now - 1,),
        )
        conn.commit()
        conn.close()

        receiver = FakeEventReceiver()
        receiver.start()
        try:
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=1,
                current_state="idle",
                previous_snapshot={"ended_sessions": [], "checked_at": now - 10},
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )

            assert current_state == "thinking"
            assert last_id == 2
            state_events = [e for e in receiver.received_events if e["event_type"] == "state_change"]
            assert state_events[-1]["state"] == "thinking"
            assert state_events[-1]["payload"]["dominant_session_id"] == "s1"
        finally:
            receiver.stop()

    def test_poll_detects_session_end_without_new_message(self, tmp_path):
        """A session ending in the sessions table emits done even when messages has no new row."""
        import sqlite3

        db_path = tmp_path / "ended_without_message.db"
        now = 1000.0
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        conn.execute("INSERT INTO sessions (id, source, started_at, ended_at) VALUES ('s1', 'cli', 900.0, NULL)")
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, 's1', 'assistant', 'Working', ?)",
            (now - 2,),
        )
        conn.commit()
        conn.close()

        current_state, prev_snapshot, last_hb, last_id = _poll(
            db_path=str(db_path),
            overlay_url="http://127.0.0.1:0/event/",
            last_seen_id=1,
            current_state="thinking",
            previous_snapshot=None,
            now=now,
            last_heartbeat_time=now,
            heartbeat_interval=5.0,
        )

        assert prev_snapshot == {"ended_sessions": [], "checked_at": now}

        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE sessions SET ended_at = ? WHERE id = 's1'", (now + 1,))
        conn.commit()
        conn.close()

        receiver = FakeEventReceiver()
        receiver.start()
        try:
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=1,
                current_state=current_state,
                previous_snapshot=prev_snapshot,
                now=now + 2,
                last_heartbeat_time=last_hb,
                heartbeat_interval=5.0,
            )

            assert current_state == "done"
            assert prev_snapshot == {"ended_sessions": ["s1"], "checked_at": now + 2}
            done_events = [e for e in receiver.received_events if e["state"] == "done"]
            assert done_events[-1]["payload"]["session_id"] == "s1"
        finally:
            receiver.stop()

    def test_poll_detects_session_end_with_new_message(self, tmp_path):
        """A session ending w/ ended_at outside infer_state's 3s done window, while another
        session has a new message, still emits done via has_session_just_ended detection."""
        import sqlite3

        db_path = tmp_path / "ended_with_new_msg.db"
        now = 1000.0
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        # s1: ended 5s ago (outside infer_state's 3s done window), with old message
        conn.execute("INSERT INTO sessions (id, source, started_at, ended_at) VALUES ('s1', 'cli', 900.0, ?)", (now - 5,))
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, 's1', 'assistant', 'Final answer', ?)",
            (now - 8,),
        )
        # s2: active, with new user message — this takes the new-message branch
        conn.execute("INSERT INTO sessions (id, source, started_at) VALUES ('s2', 'cli', 950.0)")
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (2, 's2', 'user', 'Next question', ?)",
            (now - 1,),
        )
        conn.commit()
        conn.close()

        receiver = FakeEventReceiver()
        receiver.start()
        try:
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=1,
                current_state="thinking",
                previous_snapshot={"ended_sessions": [], "checked_at": now - 10},
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )

            assert current_state == "done"
            assert last_id == 2  # cursor still advances for s2's message
            done_events = [e for e in receiver.received_events if e["state"] == "done"]
            assert len(done_events) >= 1
            assert done_events[-1]["payload"]["session_id"] == "s1"
        finally:
            receiver.stop()

    def test_poll_session_end_with_active_new_message_prefers_active_state(self, tmp_path):
        """An ended session must not hide active work from another session."""
        import sqlite3

        db_path = tmp_path / "ended_with_active_msg.db"
        now = 1000.0
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        conn.execute("INSERT INTO sessions (id, source, started_at, ended_at) VALUES ('s1', 'cli', 900.0, ?)", (now - 5,))
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, 's1', 'assistant', 'Final answer', ?)",
            (now - 8,),
        )
        conn.execute("INSERT INTO sessions (id, source, started_at) VALUES ('s2', 'cli', 950.0)")
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (2, 's2', 'assistant', 'Still working', ?)",
            (now - 1,),
        )
        conn.commit()
        conn.close()

        receiver = FakeEventReceiver()
        receiver.start()
        try:
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=1,
                current_state="idle",
                previous_snapshot={"ended_sessions": [], "checked_at": now - 10},
                now=now,
                last_heartbeat_time=now,
                heartbeat_interval=5.0,
            )

            assert current_state == "thinking"
            assert last_id == 2
            state_events = [e for e in receiver.received_events if e["event_type"] == "state_change"]
            assert state_events[-1]["state"] == "thinking"
            assert state_events[-1]["payload"]["dominant_session_id"] == "s2"
        finally:
            receiver.stop()

    def test_poll_sends_idle_heartbeat_after_done_when_no_sessions_active(self, tmp_path):
        """A completed idle system still emits heartbeats so the overlay stays connected."""
        import sqlite3

        db_path = tmp_path / "done_heartbeat.db"
        now = 1000.0
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT, started_at REAL, ended_at REAL)")
        conn.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, timestamp REAL)")
        conn.execute("INSERT INTO sessions (id, source, started_at, ended_at) VALUES ('s1', 'cli', 900.0, ?)", (now - 5,))
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, timestamp) VALUES (1, 's1', 'assistant', 'Done', ?)",
            (now - 6,),
        )
        conn.commit()
        conn.close()

        receiver = FakeEventReceiver()
        receiver.start()
        try:
            current_state, prev_snapshot, last_hb, last_id = _poll(
                db_path=str(db_path),
                overlay_url=receiver.url,
                last_seen_id=1,
                current_state="done",
                previous_snapshot={"ended_sessions": ["s1"], "checked_at": now - 5},
                now=now,
                last_heartbeat_time=now - 10,
                heartbeat_interval=5.0,
            )

            assert current_state == "idle"
            heartbeats = [e for e in receiver.received_events if e["event_type"] == "heartbeat"]
            assert len(heartbeats) == 1
            assert heartbeats[0]["state"] == "idle"
            assert heartbeats[0]["payload"]["session_active"] is False
        finally:
            receiver.stop()
