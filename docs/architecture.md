# Hermes Pet — Architecture

**Date:** 2026-05-22
**Version:** 1.0 (public release)
**Project:** Hermes Pet — a floating desktop companion for Hermes Agent on Windows

---

## 1. System Overview

Hermes Pet is a **two-process** system that bridges Hermes Agent (running inside WSL2) to a transparent Windows desktop overlay. A Python bridge polls Hermes Agent's SQLite state database inside WSL, infers the agent's current state, and pushes state-change events over HTTP to a .NET WPF overlay that renders animated sprites or debug text.

```
┌─ WSL2 (Ubuntu) ───────────────────────────────────────────────────────┐
│                                                                        │
│  ┌─────────────────────┐       ┌──────────────────────────────┐       │
│  │ Hermes Agent        │       │ bridge_watcher.py (Python)   │       │
│  │ (phantom profile)   │       │                              │       │
│  │                     │       │  1. Polls state.db every 1s  │       │
│  │  ~/.hermes/         │──────▶│  2. Reads live_state columns │       │
│  │  profiles/phantom/  │       │  3. Infers state from msgs   │       │
│  │    state.db         │       │  4. HTTP POSTs events        │       │
│  │    config.yaml      │       │  5. Persists cursor JSON     │       │
│  └─────────────────────┘       └──────────────┬───────────────┘       │
│                                                │                       │
│                         HTTP POST → http://<WINDOWS_HOST>:5731/event/ │
│                                                │                       │
└────────────────────────────────────────────────┼───────────────────────┘
                                                 │
                     Windows firewall allows      │ TCP :5731
                                                 │
┌─ Windows 11 ───────────────────────────────────┼───────────────────────┐
│                                                 ▼                       │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ HermesPet.exe (.NET 8 WPF Overlay)                              │  │
│  │                                                                │  │
│  │  ┌────────────┐  ┌────────────────┐  ┌─────────────────────┐  │  │
│  │  │ Program.cs │─▶│ MainWindow.xaml│─▶│ EventReceiver.cs    │  │  │
│  │  │ (entry)    │  │ (dual UI)      │  │ (TCP listener, bg)  │  │  │
│  │  └────────────┘  └───────┬────────┘  └─────────────────────┘  │  │
│  │                           │                                    │  │
│  │  ┌────────────────────────▼─────────────────────────────┐     │  │
│  │  │ PetEngine.cs  ◄──  PetAssetManager.cs  ◄── assets/   │     │  │
│  │  │ State→display │     Sprite loader     │     pet.json  │     │  │
│  │  └──────────────────────────────────────────────────────┘     │  │
│  │                                                                │  │
│  │  ┌──────────────────────────────────────────────────┐          │  │
│  │  │ BridgeSupervisor.cs (optional WSL process mgmt)  │          │  │
│  │  └──────────────────────────────────────────────────┘          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Key Design Properties

| Property | Value |
|----------|-------|
| Transport | HTTP POST (JSON) over TCP |
| Port | 5731 |
| Poll interval | 1 second |
| Heartbeat interval | 5 seconds (idle only) |
| State freshness | 30 seconds for live_state, 10 seconds for transcript |
| Latency | ~1s (poll-bound) |
| Bootstrapping | Fast-forward on startup to avoid replaying old messages |

---

## 2. Component Map

```
$PROJECT_ROOT/
├── src/
│   ├── bridge_watcher.py          # Main polling loop (WSL Python)
│   ├── state_mapper.py            # DB query + state inference logic
│   ├── event_schema.py            # Event validation + builder
│   ├── bridge_watcher_state.json  # Cursor persistence (auto-created)
│   └── wpf/HermesPet/             # .NET 8 WPF project
│       ├── Program.cs             # Entry point, CLI arg parsing, singleton mutex
│       ├── MainWindow.xaml        # Dual-mode layout (PET + DEBUG panels)
│       ├── MainWindow.xaml.cs     # Window logic, context menu, animation loop
│       ├── EventReceiver.cs       # TCP-based HTTP server (background thread)
│       ├── PetEngine.cs           # State → display mapping (color, speech, frames)
│       ├── PetAssetManager.cs     # Sprite sheet loader + pet manifest parser
│       └── BridgeSupervisor.cs    # WSL bridge process lifecycle management
├── tests/
│   ├── test_event_schema.py       # Event JSON validation tests
│   ├── test_state_mapper.py       # State inference unit tests
│   ├── test_bridge_watcher.py     # Bridge integration tests (mock DB)
│   ├── test_live_state.py         # Live-state lifecycle tests
│   ├── test_event_protocol.py     # Send/receive protocol tests
│   └── test_multi_session.py      # Multi-session aggregation tests
├── assets/pets/
│   └── border-collie-v2/           # Default pet sprite set (Codex Pet Share)
├── bin/
│   ├── hermes-pet                 # Shell control script (WSL)
│   ├── hermes-pet.bat             # Batch launcher (Windows CMD)
│   ├── hermes-pet.ps1             # PowerShell launcher
│   └── create-desktop-shortcut.ps1
└── docs/
    ├── architecture.md            # This file
    └── event_protocol_draft.md    # Full JSON event schema
```

---

## 3. Data Flow

### 3.1 End-to-End Event Pipeline

```
state.db ──[poll]──▶ bridge_watcher.py ──[HTTP POST]──▶ EventReceiver.cs ──[event]──▶ MainWindow.xaml.cs
   ▲                           │                                                         │
   │                           │                                                         │
   └──── Hermes Agent ─────────┘                                                         │
                                                                                         ▼
                                                                                    PetEngine.cs
                                                                                    (state → display)
```

1. **Hermes Agent** writes session data to `~/.hermes/profiles/phantom/state.db`. With [live-state support (PR #30247)](https://github.com/NousResearch/hermes-agent/pull/30247), it also writes `live_state` columns on the `sessions` table during each lifecycle phase.

2. **bridge_watcher.py** opens the SQLite DB every 1 second and calls into `state_mapper.py`:
   - First tries `get_live_states()` — reads fresh `live_state` from the sessions table.
   - If no live_state columns exist or all are stale, falls back to `infer_global_state()` — transcript-based inference from recent messages.
   - Detects session-ended transitions via `has_session_just_ended()` (snapshot comparison).
   - Builds an event dict via `build_event()` from `event_schema.py`.
   - Sends the event via HTTP POST to the Windows overlay.

3. **EventReceiver.cs** runs `TcpListener` on a background thread, accepts connections, parses the HTTP POST body as JSON, validates that `event_type` and `state` fields exist, and fires the `OnEvent` C# event.

4. **MainWindow.xaml.cs** subscribes to `OnEvent` and calls `Dispatcher.Invoke(() => UpdateDisplay(...))` to marshal the update onto the UI thread. `UpdateDisplay` calls `PetEngine.MapState()` to produce a `PetDisplayState` with colors, speech text, and animation frames.

### 3.2 Cursor-Based Polling

The bridge tracks which messages it has already seen using a **cursor** (last-seen message ID) persisted to `src/bridge_watcher_state.json`:

```json
{
  "last_seen_id": 8741,
  "current_state": "thinking",
  "db_snapshot": { "ended_sessions": [...], "checked_at": ... },
  "checked_at": 1747891234.567,
  "last_heartbeat_time": 1747891234.567
}
```

Each poll iteration:
1. Calls `get_new_messages(db_path, after_id=last_seen_id)` — fetches messages with `id > last_seen_id`.
2. If new messages exist, infers state, sends event, advances `last_seen_id` to `max(new_msgs[id])`.
3. If no new messages, checks for session-ended transitions, state expiry (timeout), and optional heartbeat emission.

### 3.3 Fast-Forward on Startup

When the bridge starts with `last_seen_id=0` (fresh state), it calls `_fast_forward()`:

```python
def _fast_forward(db_path, last_seen_id, max_gap=1000):
    max_id = SELECT MAX(id) FROM messages
    if max_id - last_seen_id > max_gap:
        return max(max_id - 100, 0)  # skip to 100 IDs behind latest
    return last_seen_id
```

This prevents the bridge from slowly replaying thousands of historical messages one-at-a-time every second.

---

## 4. Live-State Contract

### 4.1 Hermes Core DB Schema

Hermes Agent can optionally write four columns to the `sessions` table:

| Column | Type | Description |
|--------|------|-------------|
| `live_state` | TEXT | Current agent state: `listening`, `thinking`, `tool_running`, `waiting_for_jack`, `done`, `error`, `idle`, `unknown` |
| `live_state_updated_at` | REAL | Unix timestamp of latest state write |
| `current_tool_name` | TEXT | Tool name during `tool_running` (nullable) |
| `live_state_detail` | TEXT | Optional detail like error message (nullable) |

These columns are **nullable** and **backward-compatible**. If they don't exist (Hermes Agent without [PR #30247](https://github.com/NousResearch/hermes-agent/pull/30247)), the bridge silently falls back to transcript inference.

### 4.2 Lifecycle (as written by Hermes Agent)

```
User sends message      →  live_state = listening       (current_tool_name = null)
     ↓
LLM API call starts     →  live_state = thinking        (current_tool_name = null)
     ↓
Tool begins execution   →  live_state = tool_running    (current_tool_name = "read_file")
     ↓
Tool completes          →  live_state = thinking        (current_tool_name = null)  [next model iteration]
     ↓
Turn finishes           →  live_state = done            (current_tool_name = null)
     ↓  (after freshness window)
Idle timeout            →  live_state = idle            (current_tool_name = null)
```

### 4.3 Bridge Reading Live-State

`state_mapper.py::get_live_states()` queries sessions with `live_state IS NOT NULL AND live_state_updated_at >= (now - 30s)`. Returns a dict of session_id → `{state, tool_name, detail, age}`.

Freshness window: 30 seconds (`LIVE_STATE_FRESHNESS_SECONDS`). If Hermes stops writing live_state for >30s, the bridge treats it as stale and falls back to transcript inference.

### 4.4 Priority When Live-State Is Present

Live-state always takes precedence over transcript inference when fresh. The bridge uses a **priority-based aggregation** (see §6) to pick the dominant state across all sessions.

If live-state is used, the bridge marks the event with `_live_state_source: "live_state"` in the payload. The overlay can display this in DEBUG mode for debugging.

---

## 5. Fallback: Transcript-Based Inference

When live-state columns are absent or stale, `state_mapper.py::infer_global_state()` infers agent state from recent message timestamps and roles.

### 5.1 Inference Rules

| Condition | Mapped State |
|-----------|--------------|
| No messages at all | `idle` |
| Newest message is `role='user'`, age ≤ idle_threshold (10s) | `listening` |
| Newest message is `role='assistant'`, age ≤ thinking_fresh (3s) | `thinking` |
| Newest message is `role='tool'`, age ≤ tool_fresh (3s) | `tool_running` |
| Session `ended_at` just set, age ≤ 3s, content has error keywords | `error` |
| Session `ended_at` just set, age ≤ 3s | `done` |
| Stale messages (age > idle_threshold) | `idle` |
| Any other condition | `idle` |

### 5.2 Known Limitations (Transcript Only)

| State | Detectable? | Notes |
|-------|------------|-------|
| `idle` | ✅ | No recent messages or sessions |
| `listening` | ⚠️ | Heuristic: newest user message ≤ 10s ago. Not guaranteed if Hermes hasn't written a user message yet. |
| `thinking` | ✅ | Recent assistant message with content |
| `tool_running` | ✅ | Recent tool message |
| `waiting_for_jack` | ❌ | Cannot distinguish from listening without live_state |
| `done` | ✅ | Session just transitioned to ended |
| `error` | ⚠️ | Content keyword matching (error/exception/failed/traceback) |

The bridge has additional timeout heuristics for the no-new-messages branch:
- If previously `thinking` or `tool_running` and no new messages for `DEFAULT_IDLE_THRESHOLD_SECONDS` (10s), transitions to `idle`.
- Session-ended detection via snapshot comparison in `has_session_just_ended()`.

---

## 6. Multi-Session Aggregation

Hermes Agent can have multiple concurrent sessions. The bridge groups messages by `session_id` and computes a **per-session state** for each, then aggregates to a **global state** using static priority ordering.

### 6.1 Per-Session Inference

For each session (or `_orphan` group for messages without a session_id), `infer_state()` runs independently — same rules as §5.1.

### 6.2 Priority-Based Aggregation

```python
_STATE_PRIORITY = {
    "error":            100,
    "tool_running":      90,
    "thinking":          80,
    "waiting_for_jack":  70,
    "listening":         60,
    "done":              50,
    "idle":              10,
    "unknown":            0,
}
```

The global state is the per-session state with the **highest priority**. This means:
- An `error` in any session dominates the display.
- `tool_running` beats `thinking` beats `listening`.
- A busy session overrides an idle one.

### 6.3 Metadata Sent to Overlay

The bridge includes in every event:
- `active_session_count` — number of non-idle sessions.
- `dominant_session_id` — the session driving the global state (truncated stable hash).
- `per_session` — full mapping of session_id → state (for DEBUG display).
- `_live_state_source` — `"live_state"` or `"transcript_fallback"`.

The overlay renders `active_session_count` in PET mode (e.g., `thinking (2)`) and the full per_session map in DEBUG mode.

---

## 7. State Machine

### 7.1 Canonical States

```
                                    ┌──────────────────────────────┐
                                    │          unknown             │
                                    │  (startup, disconnect, err)  │
                                    └──────────┬───────────────────┘
                                               │ initial heartbeat
                                               ▼
┌────────┐    user message    ┌───────────┐    LLM API    ┌──────────┐
│  idle  │ ────────────────▶  │ listening │ ────────────▶ │ thinking │
│        │ ◀────────────────  │           │ ◀──────────── │          │
└────────┘   done timeout     └───────────┘               └────┬─────┘
      ▲                                                        │
      │                                                    tool call
      │                                                        ▼
      │                                               ┌──────────────┐
      │◀───────────────── done ───────────────────── │ tool_running  │
      │                                               └──────────────┘
      │                                                     │
      │                                               tool completes
      │                                                     │
      │                                              ┌──────▼──────┐
      │◀───────────────── done ──────────────────── │   thinking   │
      │                    (next iter)              └──────┬───────┘
      │                                                     │
      │                                              needs user input
      │                                                     │
      │                                              ┌──────▼──────────┐
      │                                              │ waiting_for_jack│
      │                                              └──────┬──────────┘
      │                                                     │ user responds
      │                                                     ▼
      │                                              ┌───────────┐
      │◀──────────────────────────────────────────── │ listening │
      │                                               └───────────┘
      │
      │  ┌───────┐
      └──│ done  │ ─── 2s auto-transition ──▶ idle
         └───────┘

  error can originate from any state
  unknown shown on startup, bridge disconnect, or DB errors
```

### 7.2 Display Mapping

| State | Pet Emotion | Animation | Accessory | Speech Bubble |
|-------|-------------|-----------|-----------|---------------|
| `idle` | Neutral, calm | idle_breathe | None | (none) |
| `listening` | Attentive | listen_pulse | Microphone | "Listening..." |
| `thinking` | Focused | think_loop | Brain icon | message_preview | Thinking..." |
| `tool_running` | Concentrated | work_loop | tool_name icon | "{tool_name}..." |
| `waiting_for_jack` | Expectant | attention_loop | Question mark | "Waiting for you..." |
| `done` | Happy | success_loop | Checkmark | "Done!" (2s auto-clear) |
| `error` | Concerned | error_loop | Warning | "Something went wrong" |
| `unknown` | Confused | unknown_idle | Question | "..." |

### 7.3 Auto-Transitions

| From | To | Trigger |
|------|----|---------|
| `done` | `idle` | 2 seconds after entry (overlay side) |
| `thinking`/`tool_running` | `idle` | No new messages for 10s (transcript timeout) |
| `listening`/`waiting_for_jack` | `idle` | No new messages for 10s (transcript timeout) |
| Any | `error` | DB read failure or event with error state |
| Any | `unknown` | No event received for 15s (overlay connection timer) |
| (startup) | `idle` | First successful poll with no activity |

### 7.4 Click-Through Behavior

The overlay is click-through (mouse events pass through to windows underneath) when idle/done/unknown, and clickable (interactive) when listening/thinking/tool_running/waiting_for_jack/error. Controlled by `IsHitTestVisible` in `PetEngine.cs`:

```csharp
ClickThrough = state is "idle" or "done" or "unknown",
```

When click-through, the overlay's `Background` is `Transparent` and `IsHitTestVisible` is false on the root container except the pet area.

---

## 8. WSL2 Networking

### 8.1 The Problem

The Python bridge runs inside WSL2, which has its own virtual network interface. `127.0.0.1` inside WSL refers to the WSL VM, not Windows. The Windows overlay cannot listen on a WSL 127.0.0.1 address, and the WSL bridge cannot reach Windows `127.0.0.1`.

### 8.2 Solution: Listen on 0.0.0.0 + Dynamic Host Discovery

**Overlay side (EventReceiver.cs):** The `TcpListener` binds to `IPAddress.Any` (0.0.0.0), not `127.0.0.1`. This makes it reachable from the WSL network namespace.

```csharp
_listener = new TcpListener(IPAddress.Any, _port);
```

**Bridge side (BridgeSupervisor.cs):** When the overlay starts the bridge process, it dynamically discovers the Windows host IP using `ip route`:

```bash
WINDOWS_HOST=$(ip route show default | awk '{print $3}')
OVERLAY_URL=http://${WINDOWS_HOST}:5731/event/
python3 src/bridge_watcher.py --overlay-url "$OVERLAY_URL"
```

The `ip route show default | awk '{print $3}'` command extracts the default gateway IP inside WSL, which is the Windows host's virtual network adapter.

**Manual mode:** When starting the bridge independently (without the supervisor), the user can pass `--overlay-url http://127.0.0.1:5731/event/` only if running the bridge with `--bridge-in-windows` flag or through WSL's `localhost` forwarding (Windows 10 + WSL2 with `[wsl2] localhostForwarding=true` in `.wslconfig`). The recommended approach for manual mode is to use the dynamic host discovery from within WSL.

### 8.3 Firewall Considerations

The overlay listens on TCP port 5731 on all interfaces. Windows Firewall may prompt for access the first time. Since traffic originates from WSL's virtual network adapter (same machine), it's safe to allow.

---

## 9. One-EXE Supervisor Mode

### 9.1 Default: Managed Bridge

When `HermesPet.exe` starts without `--no-bridge`, it instantiates `BridgeSupervisor` in the constructor of `MainWindow`:

```csharp
_bridgeSupervisor = new BridgeSupervisor(port);
_bridgeSupervisor.OnStatusChanged += OnBridgeStatusChanged;
_bridgeSupervisor.Start();
```

`BridgeSupervisor.Start()`:
1. Builds a WSL command string with dynamic host discovery and the path to `bridge_watcher.py`.
2. Launches `wsl.exe bash -lc "<command>"` as a child process.
3. Hooks stdout/stderr for logging.
4. Monitors process exit and fires status change events.

### 9.2 Process Lifecycle

```
HermesPet.exe starts
  ├── BridgeSupervisor.Start()
  │     └── wsl.exe bash -lc "cd ... && python3 src/bridge_watcher.py ..."
  │           └── bridge_watcher.py runs as child process of wsl.exe
  │
  ├── Connection timer (2s interval) monitors:
  │     ├── Last event received (10s timeout → "Not connected")
  │     └── Bridge process liveness
  │
  └── HermesPet.exe closes
        └── BridgeSupervisor.Dispose() → Stop()
              └── process.Kill(entireProcessTree: true)
```

### 9.3 Connection Status States

| Status | Meaning |
|--------|---------|
| `NotConnected` | Initial state or bridge stopped |
| `Starting` | Bridge process launched, waiting for first event |
| `Connected` | At least one event received from bridge |
| `BridgeExited` | WSL bridge process terminated |
| `WslUnavailable` | `wsl.exe` not found or failed to launch |
| `DbMissing` | `state.db` path does not exist (detected by bridge) |

### 9.4 Manual Mode

Pass `--no-bridge` to run the overlay standalone. Useful for:
- Running the bridge separately in a terminal for debugging.
- Custom bridge configurations (different profiles, ports).
- Development — running overlay locally while editing.

---

## 10. Dual Mode: PET vs DEBUG

### 10.1 PET Mode (Default)

Renders the pet character using either:
- **Sprite sheets**: Loaded from `assets/pets/<name>/spritesheet.png` with `pet.json` manifest defining frame indices per state. Cropped via `CroppedBitmap` at cell boundaries.
- **Built-in renderer**: WPF `Canvas` draws circles for body/eyes/pupils and paths for mouths — procedurally generated, no external assets needed.

Window size: 240×240px. Transparent background, always-on-top.

Features:
- Right-click context menu (switch mode, reload assets, select pet, manual state, reposition, exit).
- Left-click drag to move window.
- Connection status dot (bottom-right, color-coded).
- Optional debug overlay text (state name + session count) toggled from context menu.

### 10.2 DEBUG Mode

Shows a compact status panel with:
- Current state name and color swatch.
- Connection status or live-state source indicator.
- Speech/message preview text.
- Event counter.
- Session count.
- Current mode label (PET/DEBUG).

Window size: 280×220px. Semi-transparent dark background with green accent border.

### 10.3 Switching Modes

Right-click → "Switch to DEBUG Mode" / "Switch to PET Mode". The mode is toggled in `MainWindow.xaml.cs::ToggleMode()`:

```csharp
private void ToggleMode()
{
    _petMode = !_petMode;
    _engine.PetMode = _petMode;
    UpdateModeVisibility();  // swaps panel visibility, resizes window
    UpdateDisplay(_engine.CurrentState ?? "idle", null);
}
```

---

## 11. Threading Model

### 11.1 EventReceiver Background Thread

`EventReceiver.Start()` is called from a dedicated background thread (not the UI thread):

```csharp
_receiverThread = new Thread(() => _receiver.Start())
{
    IsBackground = true,  // won't prevent process exit
    Name = "EventReceiver"
};
_receiverThread.Start();
```

Inside `EventReceiver`:
- `AcceptLoop()` runs a `while (_running)` loop calling `TcpListener.AcceptTcpClient()` synchronously.
- Each accepted client is dispatched to `ThreadPool.QueueUserWorkItem(ProcessClient, client)` — concurrent request handling without blocking the accept loop.
- `ProcessClient` reads the HTTP request, parses JSON, validates fields, and fires the `OnEvent` event — still on the thread-pool thread.

### 11.2 UI Thread Marshalling

The `OnEvent` handler in `MainWindow.xaml.cs` uses `Dispatcher.Invoke()` to marshal the update onto the WPF UI thread:

```csharp
private void OnPetEvent(object? sender, PetEventEventArgs e)
{
    _bridgeSupervisor?.NotifyEventReceived();
    Dispatcher.Invoke(() =>
    {
        _eventCount++;
        UpdateDisplay(e.State, e.Payload);
    });
}
```

This ensures all WPF UI updates (changing text, colors, animation frames) happen on the STA thread as required by WPF.

### 11.3 Animation Timer

A `DispatcherTimer` (runs on the UI thread) fires every 300ms (or per-frame duration) to cycle through animation frames:

```csharp
_animTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
_animTimer.Tick += OnAnimTick;
```

`OnAnimTick` advances `_currentFrameIndex`, wraps for looping animations, calls `DrawAnimationFrame()` to update the displayed sprite or canvas. Stops automatically for single-frame states.

### 11.4 Connection Timer

A second `DispatcherTimer` (2s interval) monitors connection health:
- Checks `LastEventTicks` — if no event for 10s, shows timeout status.
- If no events ever received, shows "Waiting for events..." or bridge status.
- Runs on the UI thread; updates connection labels directly.

---

## 12. Polling Model Details

### 12.1 Bridge Poll Loop

```
while True:
    _poll()                        # single iteration
    if one_shot: break
    time.sleep(poll_interval)      # default 1.0s
```

The `_poll()` function:
1. Calls `get_new_messages(db_path, after_id)` — returns messages with `id > last_seen_id`.
2. If new messages exist, runs inference and sends state change.
3. If no new messages, checks session-ended transitions and state expiry.
4. If state is idle and heartbeat interval elapsed (5s), sends heartbeat.
5. Persists cursor to JSON file.
6. Returns updated state variables.

### 12.2 Why 1 Second?

- **Covers all state transitions**: Hermes Agent writes live_state synchronously during its lifecycle. A 1s poll catches every stage.
- **Low overhead**: SQLite query on a small DB is sub-millisecond. HTTP POST on localhost takes <10ms.
- **Battery-friendly**: 60 queries/min is negligible CPU.
- **Fast enough for visual feedback**: The 1s latency is imperceptible for the desktop overlay use case.

### 12.3 Heartbeat

Every 5 seconds while idle, the bridge sends a heartbeat event with:
- `event_type: "heartbeat"`
- `state: "idle"`
- `payload: { session_active: bool }`

The heartbeat serves as a liveness signal. If the overlay hasn't received any event for 10 seconds, it shows "No signal" and transitions to `unknown`. If 30+ seconds pass with no events, it shows a stronger disconnect warning.

### 12.4 State Expiry (Transcript Only)

When the bridge is using transcript inference and previously reported `thinking` or `tool_running`:
- It records the timestamp of the last message.
- Each poll checks if `(now - last_any_ts) > DEFAULT_IDLE_THRESHOLD_SECONDS (10s)`.
- If expired, sends `state_change → idle` with reason `"timeout"`.

This prevents the overlay from getting stuck on a stale state when Hermes finishes (or crashes) without writing a `done` or `idle` live_state.

### 12.5 Cursor Persistence

The watcher state file (`src/bridge_watcher_state.json`) is written every poll cycle via `_persist()`. This provides crash recovery — if the bridge restarts, it picks up from the last-seen message ID rather than replaying everything.

---

## 13. Event Protocol (Summary)

### 13.1 Wire Format

```json
{
  "event_type": "state_change",
  "state": "thinking",
  "timestamp": "2026-05-22T14:30:00.123Z",
  "payload": {
    "message_preview": "The capital of France is...",
    "active_session_count": 1,
    "dominant_session_id": "a1b2c3d4",
    "_live_state_source": "live_state"
  }
}
```

### 13.2 Event Types

| Type | Meaning |
|------|---------|
| `state_change` | State transition (used for all bridge-emitted events) |
| `heartbeat` | Liveness signal (idle, every 5s) |
| `message_chunk` | For future streaming use |
| `tool_start` | For future Hermes hook integration |
| `tool_result` | For future Hermes hook integration |
| `error_occurred` | For future Hermes hook integration |
| `reset` | Manual reset from overlay |

### 13.3 Required Fields

- `event_type` — must be one of the seven types above.
- `state` — must be one of the eight canonical states.
- `timestamp` — ISO 8601 UTC.

See `docs/event_protocol_draft.md` for the full JSON schema.

---

## 14. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Bridge-to-overlay transport | HTTP POST | Simple to implement and debug; no stateful connections; works across WSL→Windows NAT. |
| Overlay listener | TcpListener (raw TCP) | Avoids `http.sys` URL ACL requirements of `HttpListener`; no admin privileges needed. |
| Overlay framework | .NET 8 WPF | Best Windows-native fit for transparent always-on-top windows; single EXE with self-contained publish. |
| State detection | DB polling | Proven pattern from Hermes Telegram reporter; no changes to Hermes Agent core. |
| Live-state contract | Optional DB columns | Backward-compatible; existing Hermes installs without changes continue to work (fallback to transcript). |
| State persistence | JSON file | Simple, human-readable, survives restarts. No SQLite dependency for state alone. |
| Poll interval | 1 second | Fast enough for visual responsiveness; low overhead on DB and CPU. |
| Animation format | PNG sprite sheets + pet.json | Compatible with Codex Pet Share format; simple to create and extend. |
| Window mode | Dual (PET + DEBUG) | PET for end users, DEBUG for developers debugging state detection. |
| Bridge management | Optional supervisor | One-EXE experience by default; power users can run the bridge separately. |
| Multi-instance guard | Named mutex | Prevents accidental duplicate overlay windows. |
| Port | 5731 | Arbitrary; unlikely to conflict with common services. |

---

## 15. Future Architecture Evolution

Potential directions (not currently implemented):

- **Unix domain socket bridge**: Replace HTTP polling with a UDS stream inside WSL for lower latency and cleaner lifecycle.
- **Hermes Agent skill plugin**: A `hermes-pet` skill that emits events directly, eliminating DB polling entirely.
- **WebSocket transport**: Push-based event stream instead of polling; supports streaming message previews and tool progress.
- **Multiple overlay instances**: One pet per Hermes profile/session.
- **System tray integration**: Background service with per-profile pet instances.
- **Sprite streaming**: Load sprite sets from Codex Pet Share CDN on demand.
