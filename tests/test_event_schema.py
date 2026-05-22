"""Tests for event_schema.py — event validation."""

from __future__ import annotations

import json
import pytest
from event_schema import (
    EVENT_TYPES,
    HERMES_STATES,
    PROTOCOL_VERSION,
    PetEvent,
    SchemaError,
    build_event,
    validate_pet_event,
)


class TestValidatePetEvent:
    """Core event validation tests."""

    def test_valid_state_change(self):
        """A valid state_change event passes validation."""
        raw = {
            "event_type": "state_change",
            "state": "thinking",
            "timestamp": "2026-05-21T14:30:00.123Z",
            "payload": {"previous_state": "listening"},
        }
        event = validate_pet_event(raw)
        assert event.event_type == "state_change"
        assert event.state == "thinking"
        assert event.payload["previous_state"] == "listening"

    def test_valid_heartbeat(self):
        """A valid heartbeat event passes validation."""
        raw = build_event("heartbeat", "idle", {"session_active": False})
        event = validate_pet_event(raw)
        assert event.event_type == "heartbeat"
        assert event.state == "idle"

    def test_missing_event_type(self):
        """Missing event_type raises SchemaError."""
        raw = {"state": "idle", "timestamp": "2026-05-21T00:00:00Z"}
        with pytest.raises(SchemaError, match="event_type"):
            validate_pet_event(raw)

    def test_empty_event_type(self):
        """Empty event_type raises SchemaError."""
        raw = {"event_type": "", "state": "idle", "timestamp": "2026-05-21T00:00:00Z"}
        with pytest.raises(SchemaError, match="event_type"):
            validate_pet_event(raw)

    def test_invalid_event_type(self):
        """Unknown event_type values are rejected."""
        raw = build_event("invalid_event", "idle")
        with pytest.raises(SchemaError, match="event_type"):
            validate_pet_event(raw)

    def test_missing_state(self):
        """Missing state raises SchemaError."""
        raw = {"event_type": "state_change", "timestamp": "2026-05-21T00:00:00Z"}
        with pytest.raises(SchemaError, match="state"):
            validate_pet_event(raw)

    def test_empty_state(self):
        """Empty state raises SchemaError."""
        raw = {"event_type": "state_change", "state": "", "timestamp": "2026-05-21T00:00:00Z"}
        with pytest.raises(SchemaError, match="state"):
            validate_pet_event(raw)

    def test_invalid_state(self):
        """Unknown state values are rejected."""
        raw = build_event("state_change", "invalid_state")
        with pytest.raises(SchemaError, match="state"):
            validate_pet_event(raw)

    def test_missing_timestamp(self):
        """Missing timestamp raises SchemaError."""
        raw = {"event_type": "state_change", "state": "idle"}
        with pytest.raises(SchemaError, match="timestamp"):
            validate_pet_event(raw)

    def test_empty_timestamp(self):
        """Empty timestamp raises SchemaError."""
        raw = {"event_type": "state_change", "state": "idle", "timestamp": ""}
        with pytest.raises(SchemaError, match="timestamp"):
            validate_pet_event(raw)

    def test_non_dict_payload(self):
        """Non-dict payload raises SchemaError."""
        raw = {
            "event_type": "state_change",
            "state": "idle",
            "timestamp": "2026-05-21T00:00:00Z",
            "payload": "not_a_dict",
        }
        with pytest.raises(SchemaError, match="payload"):
            validate_pet_event(raw)

    def test_minimal_event(self):
        """A minimal event with no payload passes."""
        raw = build_event("reset", "idle")
        event = validate_pet_event(raw)
        assert event.event_type == "reset"
        assert event.payload == {}

    def test_not_a_dict(self):
        """Non-dict input raises SchemaError."""
        with pytest.raises(SchemaError, match="dict"):
            validate_pet_event("not a dict")  # type: ignore

    def test_all_states_accepted(self):
        """All 8 HERMES_STATES are accepted as valid state values."""
        for state in sorted(HERMES_STATES):
            raw = build_event("state_change", state)
            event = validate_pet_event(raw)
            assert event.state == state

    def test_all_event_types_accepted(self):
        """All EVENT_TYPES are accepted."""
        for etype in sorted(EVENT_TYPES):
            payload = {}
            if etype == "message_chunk":
                payload = {"text": "hello", "final": False}
            elif etype == "tool_start":
                payload = {"tool_name": "bash"}
            elif etype == "tool_result":
                payload = {"success": True}
            elif etype == "error_occurred":
                payload = {"error_message": "oops"}
            elif etype == "heartbeat":
                payload = {"session_active": False}
            raw = build_event(etype, "idle", payload)
            event = validate_pet_event(raw)
            assert event.event_type == etype


class TestMessageChunk:
    """message_chunk specific validation."""

    def test_message_chunk_requires_text(self):
        """message_chunk requires 'text' in payload."""
        raw = build_event("message_chunk", "thinking", {})
        with pytest.raises(SchemaError, match="text"):
            validate_pet_event(raw)

    def test_message_chunk_non_string_text(self):
        """message_chunk rejects non-string text."""
        raw = build_event("message_chunk", "thinking", {"text": 42})
        with pytest.raises(SchemaError, match="text"):
            validate_pet_event(raw)

    def test_message_chunk_valid_final(self):
        """message_chunk accepts valid final bool."""
        raw = build_event("message_chunk", "thinking",
                          {"text": "Hello", "final": True})
        event = validate_pet_event(raw)
        assert event.payload["final"] is True

    def test_message_chunk_invalid_final(self):
        """message_chunk rejects non-bool final."""
        raw = build_event("message_chunk", "thinking",
                          {"text": "Hello", "final": "yes"})
        with pytest.raises(SchemaError, match="final"):
            validate_pet_event(raw)


class TestToolStart:
    """tool_start specific validation."""

    def test_tool_start_requires_tool_name(self):
        """tool_start requires tool_name."""
        raw = build_event("tool_start", "tool_running", {})
        with pytest.raises(SchemaError, match="tool_name"):
            validate_pet_event(raw)

    def test_tool_start_empty_tool_name(self):
        """tool_start rejects empty tool_name."""
        raw = build_event("tool_start", "tool_running", {"tool_name": ""})
        with pytest.raises(SchemaError, match="tool_name"):
            validate_pet_event(raw)

    def test_tool_start_valid(self):
        """tool_start with valid tool_name passes."""
        raw = build_event("tool_start", "tool_running",
                          {"tool_name": "bash", "arguments": "ls -la"})
        event = validate_pet_event(raw)
        assert event.payload["tool_name"] == "bash"


class TestToolResult:
    """tool_result specific validation."""

    def test_tool_result_success_bool_required(self):
        """tool_result requires bool for success."""
        raw = build_event("tool_result", "thinking",
                          {"success": True, "exit_code": 0})
        event = validate_pet_event(raw)
        assert event.payload["success"] is True

    def test_tool_result_invalid_success(self):
        """tool_result rejects non-bool success."""
        raw = build_event("tool_result", "thinking",
                          {"success": "yes"})
        with pytest.raises(SchemaError, match="success"):
            validate_pet_event(raw)


class TestBuildEvent:
    """build_event helper tests."""

    def test_build_event_minimal(self):
        """build_event produces a valid minimal event."""
        raw = build_event("state_change", "idle")
        assert "event_type" in raw
        assert "state" in raw
        assert "timestamp" in raw
        assert raw["event_type"] == "state_change"
        assert raw["state"] == "idle"

    def test_build_event_with_payload(self):
        """build_event includes payload when provided."""
        raw = build_event("state_change", "thinking",
                          {"previous_state": "idle"})
        assert raw["payload"]["previous_state"] == "idle"

    def test_build_event_timestamp_format(self):
        """build_event generates ISO 8601 timestamps."""
        raw = build_event("state_change", "idle")
        ts = raw["timestamp"]
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) > 20


class TestSerialization:
    """Event serialization round-trip tests."""

    def test_round_trip_json(self):
        """Event survives JSON serialization round-trip."""
        raw = build_event("state_change", "thinking",
                          {"previous_state": "idle"})
        serialized = json.dumps(raw)
        deserialized = json.loads(serialized)
        event = validate_pet_event(deserialized)
        assert event.event_type == "state_change"
        assert event.state == "thinking"
        assert event.payload["previous_state"] == "idle"
