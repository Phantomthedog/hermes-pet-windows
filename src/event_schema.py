"""Schema definitions and validation for Hermes Pet event protocol.

Defines the wire format, valid states, event types, and payload schemas.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

PROTOCOL_VERSION = "hermes-pet-windows.v1"

# --- Valid state sets ---

HERMES_STATES = frozenset({
    "idle",
    "listening",
    "thinking",
    "tool_running",
    "waiting_for_jack",
    "done",
    "error",
    "unknown",
})

EVENT_TYPES = frozenset({
    "state_change",
    "message_chunk",
    "tool_start",
    "tool_result",
    "error_occurred",
    "heartbeat",
    "reset",
})

VALID_ACTIONS = frozenset({"update", "remove", "clear"})


# --- Exceptions ---

class SchemaError(ValueError):
    """Raised when an event payload fails schema validation."""
    pass


# --- Dataclasses ---

@dataclass
class PetEvent:
    """A validated event from the bridge watcher to the overlay."""
    event_type: str
    state: str
    timestamp: str  # ISO 8601
    payload: dict[str, Any] = field(default_factory=dict)


# --- Validation ---

def validate_pet_event(raw: dict[str, Any]) -> PetEvent:
    """Validate and normalize a raw event dict.

    Args:
        raw: Raw event dict (e.g., from JSON parse).

    Returns:
        Normalized PetEvent.

    Raises:
        SchemaError: If validation fails.
    """
    if not isinstance(raw, dict):
        raise SchemaError("event must be a dict")

    event_type = raw.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise SchemaError("event_type is required and must be a non-empty string")
    if event_type not in EVENT_TYPES:
        raise SchemaError(
            f"event_type must be one of {sorted(EVENT_TYPES)}, got {event_type!r}"
        )

    state = raw.get("state")
    if not isinstance(state, str) or not state:
        raise SchemaError("state is required and must be a non-empty string")
    if state not in HERMES_STATES:
        raise SchemaError(
            f"state must be one of {sorted(HERMES_STATES)}, got {state!r}"
        )

    timestamp = raw.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise SchemaError("timestamp is required and must be a non-empty string")

    payload = raw.get("payload", {})
    if not isinstance(payload, dict):
        raise SchemaError("payload must be a dict if present")

    # Event-type-specific validation
    _validate_event_payload(event_type, state, payload)

    return PetEvent(
        event_type=event_type,
        state=state,
        timestamp=timestamp,
        payload=payload,
    )


def _validate_event_payload(event_type: str, state: str, payload: dict) -> None:
    """Validate payload fields specific to each event type."""
    if event_type == "message_chunk":
        text = payload.get("text")
        if not isinstance(text, str):
            raise SchemaError("message_chunk payload must have 'text' string")
        if "final" in payload and not isinstance(payload["final"], bool):
            raise SchemaError("message_chunk payload 'final' must be bool")

    elif event_type == "tool_start":
        tool_name = payload.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise SchemaError("tool_start payload must have 'tool_name' string")

    elif event_type == "tool_result":
        if "success" in payload and not isinstance(payload["success"], bool):
            raise SchemaError("tool_result payload 'success' must be bool")

    elif event_type == "error_occurred":
        msg = payload.get("error_message")
        if msg is not None and not isinstance(msg, str):
            raise SchemaError("error_occurred payload 'error_message' must be string")

    elif event_type == "heartbeat":
        if "session_active" in payload and not isinstance(payload["session_active"], bool):
            raise SchemaError("heartbeat payload 'session_active' must be bool")


def build_event(
    event_type: str,
    state: str,
    payload: Optional[dict[str, Any]] = None,
    timestamp: Optional[str] = None,
) -> dict[str, Any]:
    """Build a valid event dict ready for serialization."""
    if timestamp is None:
        timestamp = _iso_timestamp()
    raw = {
        "event_type": event_type,
        "state": state,
        "timestamp": timestamp,
    }
    if payload:
        raw["payload"] = payload
    return raw


def _iso_timestamp() -> str:
    """Generate an ISO 8601 UTC timestamp string."""
    return time.strftime("%Y-%m-%dT%H:%M:%S.", time.gmtime()) + \
        f"{int(time.time() * 1000) % 1000:03d}Z"
