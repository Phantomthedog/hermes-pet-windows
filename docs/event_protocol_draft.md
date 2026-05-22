# Hermes Pet Event Protocol Draft

Status: draft
Date: 2026-05-21

## Purpose

This document defines a draft event protocol for sending Hermes agent state
changes to the Hermes pet display. The protocol is intentionally local-first and
display-oriented: it should let the pet show what Hermes is doing without
requiring the pet to understand Hermes internals, full transcripts, raw tool
arguments, or private tool output.

The core idea is:

```text
Hermes agent or bridge -> event stream -> Hermes pet display
```

Each event includes:

- `event_type`: what happened.
- `state`: the current Hermes state after the event is applied.
- `timestamp`: when the event was emitted.
- Optional `payload`: a safe display preview, tool status, error summary, or UI
  hint.

## Non-goals

- This is not a full transcript format.
- This is not a remote-control API for Hermes.
- This is not a persistent audit log.
- This should not carry raw secrets, full tool outputs, or unredacted file
  contents.

## 1. JSON Schema for Events

### Event Envelope

Every event is a JSON object. The pet display can render a reasonable state from
only the three required fields, while richer clients can use the optional
metadata and payload.

Required fields:

| Field | Type | Description |
| --- | --- | --- |
| `event_type` | string | The semantic type of event, such as `state_changed`, `tool_started`, or `error`. |
| `state` | string | Current Hermes agent state after applying this event. |
| `timestamp` | string | ISO 8601 date-time. Prefer UTC with `Z`, for example `2026-05-21T06:45:12.382Z`. |

Recommended fields:

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | string | Protocol version. Start with `1.0.0`. |
| `event_id` | string | Unique ID for this event. UUIDv7 or UUIDv4 is recommended. |
| `sequence` | integer | Monotonic event sequence number for ordering and replay. |
| `conversation_id` | string | Stable ID for the conversation or task thread. |
| `run_id` | string | Stable ID for one Hermes interaction cycle. |
| `source` | string | Emitter name, such as `hermes-agent`, `hermes-bridge`, or `test-fixture`. |
| `payload` | object | Optional event-specific display data. |

### Hermes State Enum

The `state` field must use one of the eight canonical Hermes states:

- `idle`
- `listening`
- `thinking`
- `tool_running`
- `waiting_for_jack`
- `done`
- `error`
- `unknown`

### Event Type Enum

The `event_type` field should use one of these values for v1:

| Event Type | Typical State | Meaning |
| --- | --- | --- |
| `state_changed` | any | Generic state transition when no more specific event type applies. |
| `message_preview` | `listening`, `thinking`, `waiting_for_jack`, `done` | A short sanitized text preview is available for the pet bubble. |
| `tool_started` | `tool_running` | Hermes started running a tool. |
| `tool_progress` | `tool_running` | Optional progress update for a running tool. |
| `tool_finished` | `thinking` or `done` | A tool completed successfully or stopped cleanly. |
| `waiting_for_input` | `waiting_for_jack` | Hermes needs Jack to answer, approve, or choose something. |
| `run_completed` | `done` | The interaction cycle completed successfully. |
| `error` | `error` | Hermes encountered an error. |
| `heartbeat` | current state | Liveness signal that should not restart visible animations unless the state changed. |

`event_type` and `state` are deliberately separate. `event_type` describes the
event that occurred; `state` tells the pet what visual state should be active
after the event.

### Payload Fields

The optional `payload` object carries safe display data. It should be small,
sanitized, and suitable for showing in a desktop overlay.

| Field | Type | Applies To | Description |
| --- | --- | --- | --- |
| `message_preview` | string | `message_preview`, `run_completed`, some `state_changed` events | Short sanitized message excerpt for a speech bubble. |
| `message_kind` | string | `message_preview` | Origin of the preview: `user`, `assistant`, `system`, `tool`, or `status`. |
| `tool_name` | string | `tool_started`, `tool_progress`, `tool_finished`, `error` | User-readable active tool name. |
| `tool_call_id` | string | tool events | Stable ID for one tool invocation. |
| `tool_status` | string | tool events | `starting`, `running`, `succeeded`, `failed`, or `cancelled`. |
| `progress` | number | `tool_progress` | Optional progress ratio from `0` to `1`. |
| `duration_ms` | integer | `tool_finished`, `error` | Duration of operation in milliseconds. |
| `error_message` | string | `error` | Short sanitized error summary. |
| `error_code` | string | `error` | Machine-readable error code. |
| `recoverable` | boolean | `error` | Whether Hermes can continue the run. |
| `requires_attention` | boolean | `waiting_for_input`, `error` | Whether the display should actively draw Jack's attention. |
| `input_prompt` | string | `waiting_for_input` | Short prompt asking Jack for input. |
| `display_hint` | string | any | UI intensity hint: `normal`, `subtle`, `urgent`, or `silent`. |
| `metadata` | object | any | Small scalar debug or UI hints. No raw logs. |

Payload privacy rules:

- `message_preview`, `input_prompt`, and `error_message` must be sanitized before
  emission.
- Do not emit secrets, credentials, access tokens, private keys, or full file
  contents.
- Do not emit raw tool arguments unless the producer can prove they are safe.
- Keep previews short. Suggested maximum: 240 characters.
- Prefer stable IDs and display labels over raw internal data.

### JSON Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hermes.local/schemas/pet-event.v1.json",
  "title": "Hermes Pet Event",
  "type": "object",
  "additionalProperties": false,
  "required": ["event_type", "state", "timestamp"],
  "properties": {
    "schema_version": {
      "type": "string",
      "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
      "default": "1.0.0"
    },
    "event_id": {
      "type": "string",
      "minLength": 1
    },
    "sequence": {
      "type": "integer",
      "minimum": 0
    },
    "conversation_id": {
      "type": "string",
      "minLength": 1
    },
    "run_id": {
      "type": "string",
      "minLength": 1
    },
    "source": {
      "type": "string",
      "enum": ["hermes-agent", "hermes-bridge", "pet-client", "test-fixture"]
    },
    "event_type": {
      "type": "string",
      "enum": [
        "state_changed",
        "message_preview",
        "tool_started",
        "tool_progress",
        "tool_finished",
        "waiting_for_input",
        "run_completed",
        "error",
        "heartbeat"
      ]
    },
    "state": {
      "type": "string",
      "enum": [
        "idle",
        "listening",
        "thinking",
        "tool_running",
        "waiting_for_jack",
        "done",
        "error",
        "unknown"
      ]
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "payload": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "message_preview": {
          "type": "string",
          "maxLength": 240
        },
        "message_kind": {
          "type": "string",
          "enum": ["user", "assistant", "system", "tool", "status"]
        },
        "tool_name": {
          "type": "string",
          "maxLength": 80
        },
        "tool_call_id": {
          "type": "string",
          "maxLength": 160
        },
        "tool_status": {
          "type": "string",
          "enum": ["starting", "running", "succeeded", "failed", "cancelled"]
        },
        "progress": {
          "type": "number",
          "minimum": 0,
          "maximum": 1
        },
        "duration_ms": {
          "type": "integer",
          "minimum": 0
        },
        "error_message": {
          "type": "string",
          "maxLength": 240
        },
        "error_code": {
          "type": "string",
          "maxLength": 80
        },
        "recoverable": {
          "type": "boolean"
        },
        "requires_attention": {
          "type": "boolean"
        },
        "input_prompt": {
          "type": "string",
          "maxLength": 240
        },
        "display_hint": {
          "type": "string",
          "enum": ["normal", "subtle", "urgent", "silent"]
        },
        "metadata": {
          "type": "object",
          "additionalProperties": {
            "type": ["string", "number", "integer", "boolean", "null"]
          }
        }
      }
    }
  }
}
```

## 2. State Mapping Table

The pet display should derive its primary visual state from `state`. The event
payload can refine the bubble text, tool indicator, icon, and urgency.

Required pet display dimensions:

- `emotion/expression`
- `animation_loop`
- `accessory/icon`
- `speech_bubble` or `tool_indicator`

| Hermes State | Agent Meaning | Emotion / Expression | `animation_loop` | Accessory / Icon | Speech Bubble or Tool Indicator |
| --- | --- | --- | --- | --- | --- |
| `idle` | Hermes is ready and not processing an active request. | Calm, neutral, relaxed eyes. | `idle_breathe` | None, or small connected status dot. | No bubble by default. Optional one-time "Ready". |
| `listening` | Hermes is receiving user input or waiting for the initial user message to finish. | Alert, attentive, focused eyes. | `listen_pulse` | Microphone, input cursor, or ear icon. | Bubble may show "Listening..." or sanitized user `message_preview`. |
| `thinking` | Hermes is reasoning, planning, or composing a response. | Focused, curious, slightly narrowed eyes. | `think_loop` | Thought bubble, small spinner, or brain icon. | Bubble may show "Thinking..." or assistant `message_preview`. |
| `tool_running` | Hermes is executing a tool call or external action. | Concentrated, work-focused. | `work_loop` | Tool-specific icon such as terminal, globe, file, calendar, or wrench. | Tool indicator should show `tool_name`; progress bar may use `progress`. |
| `waiting_for_jack` | Hermes needs Jack to answer, approve, clarify, or choose. | Expectant, raised brow, direct eye contact. | `attention_loop` | Question mark, hand raise, approval icon, or alert dot. | Bubble should show `input_prompt` or `message_preview`; use `requires_attention: true`. |
| `done` | Hermes completed the interaction successfully. | Satisfied, bright, small smile. | `success_loop` then `idle_breathe` | Check mark or completed badge, then none. | Bubble can show completion preview, then auto-dismiss. |
| `error` | Hermes encountered an error. | Concerned, surprised, or apologetic. | `error_loop` | Warning triangle or broken tool icon. | Bubble should show `error_message`; use urgent styling when not recoverable. |
| `unknown` | State is missing, invalid, stale, or not mapped yet. | Confused but not alarming. | `unknown_idle` | Question mark or disconnected status dot. | Bubble can show "Syncing..." or stay silent. Do not show stale text. |

### Display Timing Rules

- `idle` should be quiet and low-motion.
- `listening` should feel responsive but not urgent.
- `thinking` can loop indefinitely while the agent is reasoning.
- `tool_running` should remain active until `tool_finished`, `error`, or another
  state transition arrives.
- `waiting_for_jack` should persist until the user responds or the run is
  cancelled.
- `done` should be transient. Suggested auto-return to `idle`: 2 to 5 seconds.
- `error` should remain visible until a later non-error event or explicit
  dismissal.
- `unknown` should be used for startup, stale heartbeat, invalid state, or bridge
  disconnect.

## 3. Transport Options

The event schema is transport-agnostic. The same event object can be carried over
Unix domain socket, HTTP localhost, or WebSocket. Each transport should preserve
event ordering and avoid exposing the stream beyond the local machine unless a
future decision explicitly allows it.

### Option A: UDS for WSL

UDS means Unix domain socket. This is the strongest fit when Hermes runs inside
WSL or Linux and the first consumer is a local bridge process.

Example endpoint:

```text
/tmp/hermes-pet.sock
```

Recommended framing:

```text
<json event>\n
<json event>\n
```

Benefits:

- Local-only by default.
- Avoids TCP port selection and port conflicts.
- Works naturally for WSL/Linux producer processes.
- Efficient for a single local stream.
- File permissions can restrict which local user can connect.

Costs:

- Windows-native clients may not connect directly to WSL UDS.
- A bridge is probably needed for browser, Electron, Tauri, or Windows overlay
  clients.
- Socket lifecycle needs care. Stale socket files must be cleaned up.
- Multi-client fanout must be implemented by the producer or bridge.

Best use:

```text
Hermes in WSL -> /tmp/hermes-pet.sock -> hermes-pet bridge
```

### Option B: HTTP Localhost

HTTP is useful for status snapshots, debugging, replay, and simple clients that
do not need push updates.

Example endpoints:

```text
GET  http://127.0.0.1:8765/v1/pet/state
GET  http://127.0.0.1:8765/v1/pet/events?since=<sequence>
POST http://127.0.0.1:8765/v1/pet/events
GET  http://127.0.0.1:8765/v1/pet/health
```

Benefits:

- Easy to test with curl and browser dev tools.
- Works well for snapshots and health checks.
- Can support replay by sequence number.
- Easier for non-streaming integrations.

Costs:

- Polling can miss short visual states unless events are buffered.
- Requires choosing and managing a local port.
- Browser usage needs origin policy decisions.
- POST ingestion should require a token if anything other than Hermes can call
  it.

Best use:

```text
Pet client reconnects -> GET /v1/pet/state -> GET /v1/pet/events?since=last_sequence
```

### Option C: WebSocket

WebSocket is the best fit for a live pet UI that needs low-latency push updates.

Example endpoint:

```text
ws://127.0.0.1:8765/v1/pet/stream
```

Recommended connection behavior:

- Server sends the latest state snapshot immediately after connect.
- Server then sends each event as one JSON message.
- Client tracks `sequence`.
- Client reconnects with `last_sequence` if replay is supported.
- Server sends heartbeat events or uses ping/pong.

Benefits:

- Low-latency live updates.
- Good match for browser, Electron, Tauri, or overlay UI.
- Avoids polling.
- Supports multiple pet clients if the bridge supports fanout.

Costs:

- More lifecycle handling than HTTP polling.
- Reconnect and replay behavior must be defined.
- Browser clients need origin checks.
- Local auth may be needed even on localhost.

Best use:

```text
Hermes bridge -> ws://127.0.0.1:8765/v1/pet/stream -> pet UI
```

### Recommended v1 Transport Shape

Use UDS as the producer-side pipe and WebSocket/HTTP as bridge-facing client
APIs:

```text
Hermes agent -> UDS -> hermes-pet bridge -> WebSocket -> live pet UI
                                      -> HTTP -> snapshot, health, replay
```

This keeps Hermes simple and local while giving the display a browser-friendly
transport.

## 4. Example Event Sequences

### Sequence A: Typical Interaction Cycle

This is the expected happy path for a normal request where Hermes needs one tool
call before answering.

| Sequence | Event Type | State | Pet Display |
| --- | --- | --- | --- |
| 1 | `state_changed` | `idle` | Pet idles quietly. |
| 2 | `state_changed` | `listening` | Pet becomes attentive; input icon appears. |
| 3 | `message_preview` | `listening` | Bubble shows sanitized user request preview. |
| 4 | `state_changed` | `thinking` | Pet switches to focused thinking loop. |
| 5 | `tool_started` | `tool_running` | Work animation starts; tool indicator shows `tool_name`. |
| 6 | `tool_progress` | `tool_running` | Optional progress indicator updates. |
| 7 | `tool_finished` | `thinking` | Tool indicator clears; pet returns to thinking. |
| 8 | `message_preview` | `thinking` | Bubble previews response being composed. |
| 9 | `run_completed` | `done` | Success animation and completion preview. |
| 10 | `state_changed` | `idle` | Pet returns to quiet idle after timeout. |

Example JSONL:

```jsonl
{"schema_version":"1.0.0","sequence":1,"event_type":"state_changed","state":"idle","timestamp":"2026-05-21T06:45:00.000Z"}
{"schema_version":"1.0.0","sequence":2,"event_type":"state_changed","state":"listening","timestamp":"2026-05-21T06:45:05.100Z"}
{"schema_version":"1.0.0","sequence":3,"event_type":"message_preview","state":"listening","timestamp":"2026-05-21T06:45:06.200Z","payload":{"message_kind":"user","message_preview":"Draft the Hermes pet event protocol."}}
{"schema_version":"1.0.0","sequence":4,"event_type":"state_changed","state":"thinking","timestamp":"2026-05-21T06:45:07.000Z"}
{"schema_version":"1.0.0","sequence":5,"event_type":"tool_started","state":"tool_running","timestamp":"2026-05-21T06:45:08.250Z","payload":{"tool_name":"shell","tool_call_id":"call-1","tool_status":"starting","message_preview":"Checking docs directory."}}
{"schema_version":"1.0.0","sequence":6,"event_type":"tool_progress","state":"tool_running","timestamp":"2026-05-21T06:45:08.700Z","payload":{"tool_name":"shell","tool_call_id":"call-1","tool_status":"running","progress":0.5}}
{"schema_version":"1.0.0","sequence":7,"event_type":"tool_finished","state":"thinking","timestamp":"2026-05-21T06:45:09.010Z","payload":{"tool_name":"shell","tool_call_id":"call-1","tool_status":"succeeded","duration_ms":760}}
{"schema_version":"1.0.0","sequence":8,"event_type":"message_preview","state":"thinking","timestamp":"2026-05-21T06:45:10.000Z","payload":{"message_kind":"assistant","message_preview":"The event protocol draft is written with schema, transport options, and examples."}}
{"schema_version":"1.0.0","sequence":9,"event_type":"run_completed","state":"done","timestamp":"2026-05-21T06:45:11.000Z","payload":{"message_preview":"Protocol draft complete.","display_hint":"normal"}}
{"schema_version":"1.0.0","sequence":10,"event_type":"state_changed","state":"idle","timestamp":"2026-05-21T06:45:15.000Z"}
```

### Sequence B: Hermes Needs Jack's Decision

| Sequence | Event Type | State | Pet Display |
| --- | --- | --- | --- |
| 1 | `state_changed` | `listening` | Pet listens to the request. |
| 2 | `state_changed` | `thinking` | Pet evaluates missing information. |
| 3 | `waiting_for_input` | `waiting_for_jack` | Pet asks Jack for a decision and keeps attention state active. |
| 4 | `state_changed` | `listening` | Jack responds; pet returns to input state. |
| 5 | `state_changed` | `thinking` | Hermes resumes work. |
| 6 | `run_completed` | `done` | Pet shows success. |

Example decision event:

```json
{
  "schema_version": "1.0.0",
  "sequence": 3,
  "event_type": "waiting_for_input",
  "state": "waiting_for_jack",
  "timestamp": "2026-05-21T07:10:30.000Z",
  "payload": {
    "requires_attention": true,
    "input_prompt": "Which transport should be implemented first: UDS, HTTP, or WebSocket?",
    "display_hint": "urgent"
  }
}
```

### Sequence C: Recoverable Tool Error

| Sequence | Event Type | State | Pet Display |
| --- | --- | --- | --- |
| 1 | `tool_started` | `tool_running` | Pet shows active tool indicator. |
| 2 | `error` | `error` | Pet shows warning and short error. |
| 3 | `state_changed` | `thinking` | Hermes recovers and plans next step. |
| 4 | `tool_started` | `tool_running` | Retry or alternate tool starts. |
| 5 | `tool_finished` | `thinking` | Pet clears warning. |
| 6 | `run_completed` | `done` | Pet shows success. |

Example error event:

```json
{
  "schema_version": "1.0.0",
  "sequence": 2,
  "event_type": "error",
  "state": "error",
  "timestamp": "2026-05-21T07:15:00.000Z",
  "payload": {
    "error_code": "UDS_CONNECT_FAILED",
    "error_message": "Could not connect to the local Hermes event socket.",
    "recoverable": true,
    "requires_attention": false,
    "display_hint": "normal"
  }
}
```

### Sequence D: Heartbeat and Unknown Fallback

| Condition | Expected Pet Behavior |
| --- | --- |
| Heartbeat arrives on time | Keep current state; do not restart visible animation. |
| Heartbeat is late | Show subtle disconnected or stale indicator. |
| Heartbeat is missing beyond hard timeout | Switch to `unknown`; suppress stale speech bubbles. |
| Event has unrecognized state | Treat display state as `unknown`; log raw state for debugging only. |

Example heartbeat:

```json
{
  "schema_version": "1.0.0",
  "sequence": 101,
  "event_type": "heartbeat",
  "state": "idle",
  "timestamp": "2026-05-21T07:20:00.000Z"
}
```

## 5. Client Processing Rules

Recommended pet client behavior:

- Process events in ascending `sequence` order when `sequence` is present.
- Ignore duplicate or older events with a `sequence` less than or equal to the
  last processed sequence.
- If a sequence gap is detected, request replay if the transport supports it.
- If replay is unavailable, apply the newest event and mark debug state as
  potentially lossy.
- For `heartbeat`, update liveness without restarting animation loops unless the
  state changed.
- For `display_hint: "silent"`, suppress speech bubbles even when text is
  present.
- If payload text is absent, use the default display treatment for the current
  state.
- If `state` is missing or invalid, render `unknown`.
- Never keep a stale `message_preview`, `input_prompt`, or `error_message` after
  switching to an unrelated state.

## 6. Versioning

Use semantic versions in `schema_version`.

Suggested compatibility policy:

- Patch version: clarifications and non-behavioral schema comments.
- Minor version: optional fields or optional event types that old clients can
  ignore safely.
- Major version: required field changes, renamed fields, removed fields, or
  changed semantics.

For v1:

- Producers should emit only fields defined by the schema.
- Clients should tolerate missing recommended fields.
- Clients should treat unknown states as `unknown`.
- Clients may log unknown event types and use the supplied `state` if valid.

## 7. Security and Privacy

- Bind HTTP and WebSocket transports to `127.0.0.1` by default.
- Do not expose the event stream on the LAN without authentication.
- Do not send raw tool arguments, full outputs, secrets, or credentials.
- Sanitize all display text before emission.
- Use local tokens for browser-based HTTP/WebSocket if untrusted local pages
  could connect.
- Enforce allowed origins for browser clients.
- Prefer UDS permissions for the producer-side pipe.

## 8. Open Questions / Decisions Needed

1. Primary v1 transport:
   Should implementation start with UDS only, WebSocket only, or UDS plus a
   WebSocket/HTTP bridge?

2. Pet runtime:
   Will the pet run in WSL, Windows native, browser, Electron, Tauri, or another
   host? This determines whether UDS can be consumed directly.

3. Snapshot support:
   Should v1 include `GET /v1/pet/state` so reconnecting clients can get the
   current display state immediately?

4. Replay buffer:
   Should the bridge retain no events, the last 100 events, the last 250 events,
   or a time-windowed buffer?

5. Sequence scope:
   Should `sequence` reset per connection, per `run_id`, or remain monotonic for
   the whole Hermes process lifetime?

6. Authentication:
   Is localhost binding sufficient for development, or should v1 require a local
   token for WebSocket and HTTP clients?

7. Sanitization policy:
   What exact redaction rules should apply to `message_preview`, `input_prompt`,
   and `error_message`?

8. Tool naming:
   Should `tool_name` use internal tool IDs, user-facing labels, or both fields?

9. Animation vocabulary:
   Are `idle_breathe`, `listen_pulse`, `think_loop`, `work_loop`,
   `attention_loop`, `success_loop`, `error_loop`, and `unknown_idle` final asset
   names, or placeholders until the pet animation system defines names?

10. Attention behavior:
    Should `waiting_for_jack` use only visual attention, or can it trigger sound,
    taskbar flashing, or operating-system notifications?

11. Error lifecycle:
    Should recoverable errors auto-clear on the next non-error event, or remain
    visible until Jack dismisses them?

12. Multiple active runs:
    Can Hermes have overlapping `run_id` values? If yes, how should the pet pick
    the visible active run?

13. Heartbeat timing:
    What heartbeat cadence and stale timeout should v1 use? Proposed default:
    heartbeat every 5 seconds, stale warning after 15 seconds, hard `unknown`
    fallback after 30 seconds.

14. Accessibility:
    Should speech bubbles and tool indicators be exposed to screen readers, and
    should all animation loops respect reduced-motion settings?

15. Bridge ownership:
    Is the event bridge part of Hermes, part of the pet app, or a separate
    process/package?

## 9. Proposed v1 Defaults

These defaults are intended to make the first implementation concrete:

| Decision | Proposed Default |
| --- | --- |
| `schema_version` | `1.0.0` |
| Producer transport | UDS at `/tmp/hermes-pet.sock` |
| Live UI transport | WebSocket at `ws://127.0.0.1:8765/v1/pet/stream` |
| Snapshot endpoint | `GET http://127.0.0.1:8765/v1/pet/state` |
| Health endpoint | `GET http://127.0.0.1:8765/v1/pet/health` |
| Replay buffer | Last 250 events in bridge memory |
| Heartbeat cadence | Every 5 seconds |
| Stale warning | 15 seconds without heartbeat |
| Hard fallback | 30 seconds without heartbeat |
| Sequence scope | Monotonic per Hermes process |
| Text preview limit | 240 characters |
| Privacy stance | Sanitized previews only; no full transcripts or raw tool outputs |

