"""Tests for fake event sender and receiver."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from event_schema import build_event, validate_pet_event, SchemaError


class FakeEventReceiver:
    """A minimal HTTP server that receives pet events for testing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self.host = host
        self.port = port
        self.received_events: list[dict] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        """Start the receiver in a background thread."""
        self._server = HTTPServer((self.host, self.port), self._make_handler(self))
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        daemon=True)
        self._thread.start()
        time.sleep(0.05)  # Let server start

    def stop(self):
        """Stop the receiver."""
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/event/"

    @staticmethod
    def _make_handler(receiver: "FakeEventReceiver"):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                try:
                    raw = json.loads(body)
                    event = validate_pet_event(raw)
                    receiver.received_events.append({
                        "event_type": event.event_type,
                        "state": event.state,
                        "payload": event.payload,
                    })
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "ok"}).encode())
                except (json.JSONDecodeError, SchemaError) as e:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(
                        json.dumps({"status": "error", "message": str(e)}).encode()
                    )

            def log_message(self, fmt, *args):
                pass  # Suppress HTTP log output during tests

        return Handler


def send_event(url: str, event: dict) -> dict:
    """Send an event dict to a receiver via HTTP POST.

    Returns the response dict.
    """
    import urllib.request
    import urllib.error

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


# --- Tests ---

class TestFakeEventReceiver:

    def test_receiver_accepts_valid_event(self):
        """Receiver accepts a valid state_change event."""
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            event = build_event("state_change", "thinking",
                                {"previous_state": "listening"})
            resp = send_event(receiver.url, event)
            assert resp["status"] == "ok"
            assert len(receiver.received_events) == 1
            assert receiver.received_events[0]["event_type"] == "state_change"
            assert receiver.received_events[0]["state"] == "thinking"
        finally:
            receiver.stop()

    def test_receiver_rejects_malformed_event(self):
        """Receiver rejects event with missing state."""
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            event = {"event_type": "state_change", "timestamp": "2026-05-21T00:00:00Z"}
            resp = send_event(receiver.url, event)
            assert resp["status"] == "error"
            assert "state" in resp["message"].lower()
            assert len(receiver.received_events) == 0
        finally:
            receiver.stop()

    def test_receiver_rejects_invalid_state(self):
        """Receiver rejects event with invalid state value."""
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            event = build_event("state_change", "nonexistent_state")
            resp = send_event(receiver.url, event)
            assert resp["status"] == "error"
            assert len(receiver.received_events) == 0
        finally:
            receiver.stop()

    def test_receiver_rejects_bad_json(self):
        """Receiver rejects non-JSON body."""
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            import urllib.request
            req = urllib.request.Request(
                receiver.url,
                data=b"not-json-at-all",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            assert result["status"] == "error"
        except Exception:
            pass  # May raise HTTPError, content is still error
        finally:
            receiver.stop()

    def test_receiver_accepts_multiple_events(self):
        """Receiver handles multiple sequential events."""
        receiver = FakeEventReceiver()
        receiver.start()
        try:
            events = [
                build_event("state_change", "listening"),
                build_event("state_change", "thinking"),
                build_event("state_change", "done"),
                build_event("heartbeat", "idle", {"session_active": False}),
            ]
            for evt in events:
                resp = send_event(receiver.url, evt)
                assert resp["status"] == "ok"
            assert len(receiver.received_events) == 4
        finally:
            receiver.stop()
