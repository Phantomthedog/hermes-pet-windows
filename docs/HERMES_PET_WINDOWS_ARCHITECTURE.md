# Hermes Pet for Windows/WSL — Architecture Document

**Date:** 2026-05-21
**Version:** 0.1 (pre-implementation)
**Machine:** Windows 11 + WSL2 Ubuntu
**Hermes Profile:** phantom (default)

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ WSL (Ubuntu)                                                                │
│                                                                             │
│  ┌──────────────────────┐       ┌──────────────────────────────────────┐   │
│  │ Hermes Agent (phantom)│       │ Bridge Watcher (Python)              │   │
│  │                       │       │                                      │   │
│  │  ~/.hermes/           │       │  1. Polls state.db every 1 second    │   │
│  │  profiles/phantom/    │       │  2. Detects state transitions         │   │
│  │    state.db           │──────▶│  3. Emits JSON events via HTTP POST   │   │
│  │    config.yaml        │       │  4. Manages heartbeat timer           │   │
│  │                       │       │                                      │   │
│  └──────────────────────┘       └──────────────┬───────────────────────┘   │
│                                                 │                           │
│                                    HTTP POST http://127.0.0.1:5731/event   │
│                                                 │                           │
└─────────────────────────────────────────────────┼───────────────────────────┘
                                                   │
                      Windows firewall allows       │ 127.0.0.1:5731
                                                   │
┌──────────────────────────────────────────────────┼───────────────────────────┐
│ Windows 11                                                                  │
│                                                 │                           │
│                    ┌─────────────────────────────▼───────────────────┐      │
│                    │ Windows Floating Overlay (.NET WPF)             │      │
│                    │                                                │      │
│                    │  • Always-on-top transparent window             │      │
│                    │  • Click-through when idle                     │      │
│                    │  • Right-click menu                            │      │
│                    │  • Sprite animation (PNG sprite sheets)        │      │
│                    │  • HTTP event receiver on 127.0.0.1:5731       │      │
│                    │  • State → emotion/animation mapping           │      │
│                    └────────────────────────────────────────────────┘      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. Component Architecture

### 2.1 Bridge Watcher (WSL, Python)

**File:** `src/bridge_watcher.py`
**Runtime:** Standalone Python script in WSL

**Responsibilities:**
- Poll `state.db` every second using cursor-based approach (like Telegram reporter)
- Detect session state changes from DB schema
- Map DB state → protocol state (idle, listening, thinking, tool_running, waiting_for_jack, done, error, unknown)
- Emit events via HTTP POST to the Windows overlay
- Send heartbeats every 5 seconds when idle
- Track `last_seen_message_id` for cursor persistence
- Handle missing DB, connection errors gracefully

**State detection logic:**
- `messages.timestamp` recent + `role = 'assistant'` and content being generated → `thinking`
- `messages.role = 'tool'` recent → `tool_running`
- `sessions.ended_at IS NULL` with no messages in last 30s → `idle`
- `sessions.ended_at` just set → `done`
- Cannot directly detect `listening` or `waiting_for_jack` from DB alone (needs Hermes hook integration — defer to V2)

**Cursor persistence:** JSON file `src/bridge_watcher_state.json` storing `last_seen_message_id`

### 2.2 Windows Overlay (.NET WPF)

**File:** `src/wpf/HermesPet/` (C# project)
**Runtime:** Self-contained .NET executable

**Window behavior:**
- `WindowStyle="None"`, `AllowsTransparency="True"`, `Background="Transparent"`
- `Topmost="True"` — always on top
- `IsHitTestVisible="False"` on background, `True` only on active pet area
- Right-click menu: Show ContextMenu on hit area
- Position: bottom-right corner (configurable)
- Size: 84×84 pixels (default, matches reference 84px sprites)

**State display mapping:**

| Hermes State | Emotion | Animation | Accessory | Speech Bubble |
|---|---|---|---|---|
| idle | neutral | idle_bounce | none | (none) |
| listening | attentive | listening_pulse | mic | "Listening..." |
| thinking | thinking | thinking_dotdotdot | brain | (message preview) |
| tool_running | busy | working_bobbing | gear | (tool name) |
| waiting_for_jack | confused | tilt_head | question | "Waiting..." |
| done | happy | idle_bounce | checkmark | "Done!" (2s auto-clear) |
| error | sad | shake | error_badge | "Error" |
| unknown | neutral | glitch | question | "..." |

**HTTP listener:** `HttpListener` on `http://127.0.0.1:5731/event/`

### 2.3 Event Protocol

**Transport:** HTTP POST (JSON), `http://127.0.0.1:5731/event/`

```json
{
  "protocol": "hermes-pet-windows.v1",
  "event_type": "state_change",
  "state": "thinking",
  "timestamp": "2026-05-21T14:30:00.123Z",
  "payload": {
    "previous_state": "listening",
    "message_preview": "The capital of France is...",
    "session_id": "20260521_144307_41db..."
  }
}
```

**Event types:** state_change, message_chunk, tool_start, tool_result, error_occurred, heartbeat, reset

## 3. State Mapping Detail

### 3.1 Hermes DB → Protocol State

The state.db doesn't have an explicit state column. We infer state:

| Condition | Mapped State |
|-----------|-------------|
| No sessions with `ended_at IS NULL` in last 60s | idle |
| Session exists, `ended_at IS NULL`, newest message > 30s ago | idle |
| Session exists, newest `messages.role = 'assistant'` with content, < 5s ago | thinking |
| Session exists, newest `messages.role = 'tool'`, < 5s ago | tool_running |
| Session `ended_at` just transitioned from NULL to value | done |
| Session ended with error-related content in last message | error |
| Any other condition | unknown |

**Caveat:** `listening` and `waiting_for_jack` cannot be reliably detected from state.db alone. The bridge watcher uses `previous_state` + timeout heuristics:
- After `thinking` → no new message for 3s → assume `listening` (user typed)
- After `tool_running` → no new message for 5s → assume `waiting_for_jack`

### 3.2 Transition Rules

- Every state can transition to `error`
- `thinking` ↔ `tool_running` can loop (multiple tool calls in one response)
- `done` auto-transitions to `idle` after 2 seconds (configurable)
- `unknown` is the fallback state on startup or watcher failure
- If no event received for 15 seconds, overlay shows `unknown` with disconnect indicator

## 4. Data Flow: End-to-End Example

```
1. Bridge Watcher starts
   → Checks state.db for last message
   → Sends heartbeat (idle)

2. User starts Hermes session (CLI)
   → state.db gets new session with ended_at=NULL
   → Bridge detects: session active, no new messages
   → Sends state_change → idle (with session_active=true)

3. User sends message to Hermes
   → DB gets new user message
   → Bridge detects: newest message is user role
   → Sends state_change → listening

4. LLM starts generating
   → DB gets assistant message (growing)
   → Bridge detects: role=assistant with content
   → Sends state_change → thinking

5. Tool call executes
   → DB gets tool message
   → Bridge detects: role=tool
   → Sends state_change → tool_running

6. LLM finishes
   → Bridge detects: no new message for 2s
   → Sends state_change → done
   → After 2s: state_change → idle

7. User ends session
   → ended_at gets value
   → Bridge detects: session ended, no active session
   → Sends state_change → idle (with session_active=false)
```

## 5. File Structure

```
$PROJECT_ROOT/
├── docs/
│   ├── event_protocol_draft.md        # From Phase 1
│   └── HERMES_PET_WINDOWS_ARCHITECTURE.md  # This file
├── src/
│   ├── bridge_watcher.py              # WSL Python watcher
│   ├── bridge_watcher_state.json      # Cursor state (auto-created)
│   ├── event_schema.py                # Event type definitions + validation
│   ├── state_mapper.py                # DB → protocol state mapping
│   ├── test_events.py                 # Fake event sender (for testing)
│   └── wpf/
│       └── HermesPet/                 # .NET WPF project
│           ├── HermesPet.csproj
│           ├── Program.cs
│           ├── MainWindow.xaml
│           ├── MainWindow.xaml.cs
│           ├── PetEngine.cs           # State → emotion/animation engine
│           ├── EventReceiver.cs       # HTTP listener
│           ├── SpriteRenderer.cs      # PNG sprite sheet renderer
│           └── assets/                # Sprite PNGs
├── tests/
│   ├── test_event_schema.py           # Validate event JSON
│   ├── test_state_mapper.py           # State mapping logic
│   ├── test_bridge_watcher.py         # Bridge watcher with mock DB
│   └── test_event_protocol.py         # Send/receive event tests
├── reports/
│   ├── repo_scout.md                  # From Phase 1
│   ├── hermes_state_scout.md          # From Phase 1
│   └── windows_ui_scout.md            # From Phase 1
├── references/                        # Placeholder
└── README.md                          # Project overview
```

## 6. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Transport for MVP | HTTP (event POST) | Simplest to implement and debug. Can add WebSocket later. |
| Port | 5731 | Arbitrary, unlikely to conflict. Documented in protocol. |
| Overlay framework | .NET WPF | Best Windows-native fit. Single EXE, no runtime install. |
| Overlay runner | WSL bash helper | `dotnet run` from WSL bash script. No autostart. |
| State detection | DB polling | Reuses proven Telegram reporter pattern. No Hermes core patches needed. |
| Cursor persistence | JSON file | Simple, readable, survives restarts. |
| Sprite format | PNG sprite sheets | Compatible with Codex Pet Share format. No binary format. |
| Authentication | None (localhost-only) | Sufficient for local-only transport. No secrets. |
| Language preference | System language auto-detect | Falls back to English. Can be extended. |

## 7. Known Limitations (V1)

1. **`listening` cannot be detected from DB** — uses heuristic timeout
2. **`waiting_for_jack` cannot be detected from DB** — uses heuristic timeout
3. **No tool call correlation** — cannot link `tool_start` → `tool_result` pairs
4. **No streaming content** — only sees completed assistant messages
5. **1-second polling latency** — not real-time (acceptable for MVP)
6. **Single profile** — only watches phantom profile
7. **No autostart** — intentional for V1
8. **No Windows installer** — intentional for V1
9. **Basic sprite set** — bundled PNGs only, no Codex Pet Share import yet

## 8. Future Enhancements (Post-V1)

- **A)** Codex sprite compatibility — import sprite sheets from codex-pet-share.pages.dev
- **B)** Windows startup helper — add to Windows Task Scheduler or Startup folder
- **C)** Hermes skill wrapper — create `hermes-pet` skill for Phantom profile
- **D)** Richer state detection — Hermes hook integration for true real-time events
- **E)** Native packaging — single EXE via `dotnet publish --self-contained`
- **F)** WebSocket transport for message streaming
- **G)** Multi-profile support
- **H)** Tool call timeline display
