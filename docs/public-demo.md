# Hermes Pet — Public Demo Guide

> A floating desktop companion that brings your Hermes Agent to life on your
> Windows desktop. Animated sprites react in real time as the agent listens,
> thinks, runs tools, and responds.

**Version:** 1.0 (public release)
**Repository:** `hermes-pet` (project root)

---

## 1. First Run — What You See

When you launch Hermes Pet for the first time, a small transparent overlay
window appears in the center of your screen. No taskbar icon grabs
attention — just a soft, always-on-top circle containing the pet character.

**PET mode (default):**

- A round 240×240 px window with a transparent background.
- The pet character sits in the center — either a procedurally drawn
  blob face (built-in) or an animated spritesheet character.
- A thin status bar at the bottom shows optional speech text and a small
  connection dot (gray = disconnected, green = connected).
- The window is **click-through** when idle — mouse events pass straight
  through to whatever window is underneath. You can left-click-drag to
  reposition it.
- Right-click opens a context menu: switch mode, reload assets, select a
  different pet, send a manual test state, or exit.

**DEBUG mode (right-click → Switch to DEBUG Mode):**

- A slightly larger 280×220 px panel with a dark background
  (`#1E1E1E`) and a green (`#00FF88`) accent border.
- Shows the current agent state as a text label, the connection status /
  live-state source, a speech/message preview, an event counter, and
  the active session count.
- Useful for understanding what the bridge is seeing in real time.

---

## 2. Build & Run — Step by Step

### Requirements

| Dependency | Where | Purpose |
|------------|-------|---------|
| Windows 10/11 | Host | WPF overlay |
| WSL2 + Ubuntu | WSL | Python bridge watcher |
| .NET 8 SDK | **Windows** | Build the overlay |
| Python 3 | WSL | Bridge watcher (usually pre-installed) |
| Hermes Agent | WSL | The agent being watched |

### 2.1 Build the WPF Overlay

On **Windows** (PowerShell, CMD, or Windows Terminal):

```powershell
cd src\wpf\HermesPet
dotnet build -c Release
```

This produces `src/wpf/HermesPet/bin/Release/net8.0-windows/win-x64/HermesPet.exe`.

### 2.2 Run — One-EXE Mode (Recommended)

The overlay auto-starts the WSL bridge — no extra terminal needed.

```powershell
# From Windows (CMD):
bin\hermes-pet.bat start-all

# Or from PowerShell:
.\bin\hermes-pet.ps1 start-all
```

Or run the EXE directly:

```powershell
.\src\wpf\HermesPet\bin\Release\net8.0-windows\win-x64\HermesPet.exe
```

The EXE launches `wsl.exe bash -c "python3 src/bridge_watcher.py ..."` as a
child process with dynamic host discovery. The bridge logs go to `logs/bridge.log`.

### 2.3 Run — Manual Mode

Start the overlay standalone (no bridge):

```powershell
HermesPet.exe --no-bridge
dotnet run -- --port 5731   # from source
```

Then from **WSL**, start the bridge pointing at the Windows host:

```bash
bash bin/hermes-pet start-bridge
```

Or manually:

```bash
WINDOWS_HOST=$(ip route show default | awk '{print $3}')
python3 src/bridge_watcher.py \
  --overlay-url "http://${WINDOWS_HOST}:5731/event/"
```

### 2.4 Verify It's Working

From WSL:

```bash
bash bin/hermes-pet doctor          # checks all dependencies
bash bin/hermes-pet status          # shows overlay + bridge status
bash bin/hermes-pet test-bridge     # one-shot DB read + check
```

You should see the connection dot on the overlay turn green within a few
seconds of the bridge starting.

---

## 3. Testing with Fake Events

You don't need Hermes Agent running to see the pet in action. Send
simulated state transitions from WSL.

### 3.1 Sequence Mode

Sends a full lifecycle (idle → listening → thinking → tool_running →
waiting_for_jack → thinking → done → idle), 2 seconds between each:

```bash
bash bin/hermes-pet test-event         # runs the full sequence
```

Alternatively, the Python script directly:

```bash
python3 src/test_events.py
```

### 3.2 Single-State Mode

Send one specific state to see the pet react:

```bash
bash bin/hermes-pet test-event thinking
bash bin/hermes-pet test-event tool_running
bash bin/hermes-pet test-event done
bash bin/hermes-pet test-event error
bash bin/hermes-pet test-event listening
bash bin/hermes-pet test-event idle
```

Under the hood, this sends an HTTP POST to the overlay with a JSON body:

```json
{
  "event_type": "state_change",
  "state": "thinking",
  "timestamp": "2026-05-22T12:34:56.789Z"
}
```

---

## 4. PET Mode vs DEBUG Mode

Right-click the overlay → context menu to switch.

### PET Mode

- Renders the pet character (sprite or procedural blob).
- Animations change per state: breathing, pulsing, working, celebrating.
- Speech bubble shows tool names or preview text.
- Connection dot in the corner.
- Window is click-through when idle/done/unknown; interactive during
  active states.

### DEBUG Mode

- Text-based panel showing everything the bridge knows.
- **State label:** current Hermes state with color coding.
- **Connection label:** live-state source (`live_state` or
  `transcript_fallback`) and current tool name.
- **Speech area:** latest message preview or state detail.
- **Event counter:** number of events received since launch.
- **Session count:** number of active (non-idle) sessions.
- **Mode label:** "DEBUG" or "PET".

### Visual Comparison Table

| Aspect | PET Mode | DEBUG Mode |
|--------|----------|------------|
| Window size | 240×240 px | 280×220 px |
| Background | Transparent | `#1E1E1E` with `#00FF88` border |
| Character | Animated sprite / procedural face | Text labels |
| Click-through | Conditional on state | Never click-through |
| Best for | Ambience, end users | Debugging, development |

---

## 5. Pet Reactions — State to Animation

The pet's appearance and animation change instantly when the bridge pushes
a new state. Here is the full mapping:

| State | Built-in Face Color | Pet Emotion | Animation Style | Speech Bubble |
|-------|---------------------|-------------|-----------------|---------------|
| `idle` | Green | Neutral, calm | `idle_breathe` — slow pulse | (none) |
| `listening` | Blue | Attentive | `listen_pulse` — gentle glow | "Listening..." |
| `thinking` | Orange | Focused | `think_loop` — bouncing | Message preview |
| `tool_running` | Green | Concentrated | `work_loop` — busy motion | Tool name shown |
| `waiting_for_jack` | Yellow | Expectant | `attention_loop` — looking around | "Waiting for you..." |
| `done` | Bright green | Happy | `success_loop` — celebration | "Done!" (2s auto-clear) |
| `error` | Red | Concerned | `error_loop` — shake/frown | "Something went wrong" |
| `unknown` | Gray | Confused | `unknown_idle` — tilt | "..." |

### Auto-Transitions

The overlay itself handles some transitions:

| From | To | When |
|------|----|------|
| `done` | `idle` | 2 seconds after entry |
| Any active state | `idle` | No new events for 10s (transcript timeout) |
| Any state | `error` | On DB read failure or error event |
| Any state | `unknown` | No event received for 15s (connection lost) |
| (startup) | `idle` | First successful poll |

### Click-Through Behavior

The overlay is **click-through** (mouse passes through to windows beneath)
when in `idle`, `done`, or `unknown` states. It becomes **interactive**
during active states (`listening`, `thinking`, `tool_running`,
`waiting_for_jack`, `error`) so you can right-click to open the menu.

---

## 6. Live-State Demo — Real Hermes Query

This is the most impressive demo: run an actual Hermes query and watch the
pet cycle through states in real time.

### Prerequisites

- Hermes Agent running in WSL (the `phantom` profile is the default).
- Hermes Pet overlay + bridge running (see §2).

### 6.1 Start Everything

From Windows:

```powershell
# Or just double-click HermesPet.exe
.\bin\hermes-pet.bat start-all
```

### 6.2 Run a Hermes Query

From another WSL terminal:

```bash
hermes ask "What files are in my home directory?"
```

### 6.3 Watch the Pet Cycle

As the agent processes the request, the overlay will show:

```
listening  ───  thinking  ───  tool_running  ───  thinking  ───  done
(2-3 sec)     (5-15 sec)       (bash/ls)         (response)      ✓
```

**What to look for:**

1. **listening** — The instant you press Enter. Pet turns blue/attentive.
2. **thinking** — When the LLM API call begins. Pet turns orange, shows a
   bouncing "thinking" animation. Speech area may show message preview.
3. **tool_running** — The moment a tool executes (e.g., `search_files`,
   `bash`). Pet turns green-concentrated. Speech shows the tool name.
   Loop back to `thinking` when the tool returns.
4. **done** — The turn finishes. Pet briefly celebrates (green, happy
   animation) and auto-transitions to `idle` after 2 seconds.

If there's an error (tool crash, API failure), the pet turns red and shows
the error animation.

### 6.4 Live-State vs Transcript Fallback

In DEBUG mode, the connection label tells you which detection method is
active:

| Label | Meaning |
|-------|---------|
| `live_state` | Hermes core is writing live_state columns — fastest, most accurate |
| `transcript_fallback` | No live_state columns or stale — inferred from message timestamps |

The fallback is slightly delayed (up to 1-2 seconds) and cannot distinguish
`waiting_for_jack` from `listening`, but works with any Hermes version.

---

## 7. Adding a Custom Pet

You can add your own sprite-based pet without touching any code.

### 7.1 Directory Structure

```
assets/pets/
  your-pet-name/
    pet.json         # Manifest (required)
    spritesheet.png  # Sprite atlas (required)
```

### 7.2 The pet.json Manifest

Example (`assets/pets/border-collie-v2/pet.json`):

```json
{
  "name": "border-collie-v2",
  "display_name": "Border Collie V2",
  "version": 2,
  "attribution": "Community-shared Codex Pet",
  "cell_width": 192,
  "cell_height": 208,
  "atlas_cols": 8,
  "atlas_rows": 8,
  "frame_rate": 8,
  "states": {
    "idle":             { "frames": [8, 9, 10, 11, 12, 13],           "frame_ms": 280, "loop": true },
    "listening":        { "frames": [47, 48, 49, 50, 51, 52],         "frame_ms": 250, "loop": true },
    "thinking":         { "frames": [19, 20, 21, 22, 23, 24],         "frame_ms": 400, "loop": true },
    "tool_running":     { "frames": [41, 42, 43, 44, 45, 46],         "frame_ms": 250, "loop": true },
    "waiting_for_jack": { "frames": [53, 54, 55, 56],                 "frame_ms": 400, "loop": true },
    "done":             { "frames": [14, 15, 16, 17, 18],             "frame_ms": 250, "loop": false },
    "error":            { "frames": [0, 1, 2, 3, 4, 5, 6, 7],        "frame_ms": 200, "loop": false },
    "unknown":          { "frames": [25, 33, 26, 34, 27, 35, 28, 36], "frame_ms": 250, "loop": true }
  },
  "description": "Border Collie with per-state animations."
}
```

### 7.3 Manifest Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Internal name, used as directory name |
| `display_name` | string | Human-readable name shown in menus |
| `version` | int | Sprite pack version |
| `cell_width` | int | Width of one frame in pixels |
| `cell_height` | int | Height of one frame in pixels |
| `atlas_cols` | int | Number of columns in the spritesheet grid |
| `atlas_rows` | int | Number of rows in the spritesheet grid |
| `frame_rate` | int | Default frames per second |
| `states` | object | Map of state name → animation config |

### 7.4 State Animation Config

Each state entry in `states` has:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `frames` | int[] | (required) | Zero-based frame indices across the atlas |
| `frame_ms` | int | 300 | Milliseconds per frame |
| `loop` | bool | true | Whether the animation loops or stops on last frame |

The overlay reads frames by splitting the spritesheet into a grid of
`atlas_cols` × `atlas_rows` cells. Frame index `i` maps to
`row = floor(i / atlas_cols)`, `col = i % atlas_cols`.

### 7.5 Selecting Your Pet

Right-click the overlay → **Select Pet** → choose your pet by display name.
The overlay reloads assets from disk. If the spritesheet isn't found, it
falls back to the built-in procedural renderer gracefully.

---

## 8. Multi-Session — What It Looks Like

Hermes Agent can run multiple simultaneous sessions (e.g., CLI + Telegram +
a background task). Hermes Pet aggregates them intelligently.

### How Aggregation Works

1. The bridge groups all recent messages by `session_id`.
2. Each session gets its own inferred state using the same rules.
3. A **priority system** picks the global state:

```
error > tool_running > thinking > waiting_for_jack >
listening > done > idle > unknown
```

4. The overlay receives the **dominant state** plus metadata.

### What You See

**PET mode:** The state label (if debug overlay is on) shows `thinking (2)`
— the state name with a session count suffix indicating how many sessions
are active.

**DEBUG mode:** The connection label shows the actual per-session map.
Example:

```
live_state · sessions: 3 active
  s1: thinking
  s2: tool_running (search_files)
  s3: idle
```

The overlay always shows the highest-priority state. If session 1 is
`thinking` while session 2 is `tool_running`, the pet shows
`tool_running` because that priority wins. When session 2 finishes,
it falls back to `thinking` from session 1.

### Edge Cases

- **Error dominates:** If any session encounters an error, the pet
  immediately shows the error state regardless of other sessions.
- **Done doesn't override:** A session that just ended (`done`) won't
  hide an active `thinking` or `tool_running` in another session —
  priority ordering ensures busy work stays visible.
- **Orphan messages:** Messages without a `session_id` are grouped
  under `_orphan` and still trigger state inference.

---

## 9. Screenshot & Capture Suggestions

Since this is a desktop overlay (transparent window, always-on-top), here
are suggestions for visual documentation — no screenshots are embedded in
this document.

### 9.1 PET Mode — Idle State

**What to capture:** The overlay in PET mode with no active agent activity.
- The small round transparent window with the pet character centered.
- Built-in: a green blob face with neutral expression.
- Sprite pet: the idle animation frame (Border Collie lying down).
- Connection dot in the corner (green if bridge is running).
- No speech bubble visible.

**How to set up:** Start Hermes Pet, wait 10 seconds with no activity.

### 9.2 PET Mode — Active States (Collage)

**What to capture:** Four separate overlays showing the pet in different
states. A tiled/montage layout works well.

1. **Listening** — Blue/attentive face, "Listening..." speech text.
   Send: `bash bin/hermes-pet test-event listening`

2. **Thinking** — Orange/focused face, message preview in speech area.
   Send: `bash bin/hermes-pet test-event thinking`

3. **Tool Running** — Green/concentrated face, tool name visible.
   Send: `bash bin/hermes-pet test-event tool_running`

4. **Done** — Bright green/happy face, "Done!" speech.
   Send: `bash bin/hermes-pet test-event done`

**Tip:** Capture each screenshot 1-2 seconds after sending the event so
the animation is in a mid-cycle frame, not the first frame.

### 9.3 PET Mode — Error State

**What to capture:** The pet in error state — red face, concerned expression,
error speech bubble.

Send: `bash bin/hermes-pet test-event error`

### 9.4 DEBUG Mode Panel

**What to capture:** The DEBUG mode panel showing:
- State label: `State: thinking`
- Connection label: `live_state · tool: search_files`
- Speech preview with actual message text
- Event counter showing a non-zero count
- Session count: `Sessions: 2`

**How to set up:** Switch to DEBUG mode (right-click → "Switch to DEBUG
Mode"), then send a `tool_running` event with a tool name, or run a real
Hermes query.

### 9.5 Multi-Session View (DEBUG Mode)

**What to capture:** DEBUG mode with multiple active sessions.

1. Open two Hermes CLI sessions (or use fake events).
2. In the overlay, the connection label should show per-session states.
3. Example after sending events for two sessions:
   ```
   live_state · sessions: 2 active
     s1: thinking
     s2: tool_running (bash)
   ```

### 9.6 Context Menu

**What to capture:** The right-click context menu overlay on top of the PET
mode window. Shows menu items:
- Switch to DEBUG Mode / Switch to PET Mode
- Select Pet ▶ (submenu)
- Toggle Debug Label
- Manual State ▶ (submenu)
- Reload Assets
- Reposition
- Exit

### 9.7 Architecture Diagram

**What to create:** A simple flow diagram showing:
```
WSL:
  Hermes Agent → writes → state.db
  bridge_watcher.py → polls state.db → HTTP POST → Windows
Windows:
  HermesPet.exe ← receives events → renders pet
```

The diagram in `docs/architecture.md` §1 is a good reference.

### 9.8 Animated GIF / Screen Recording

**What to capture:** A 15-20 second screen recording showing a full
lifecycle:

1. Start: idle pet.
2. Send `bash bin/hermes-pet test-event listening` → pet turns blue.
3. Wait 2 seconds → pet turns orange (thinking).
4. Send `bash bin/hermes-pet test-event tool_running` → pet shows tool state.
5. Send `bash bin/hermes-pet test-event done` → pet celebrates.
6. Auto-transition back to idle after 2 seconds.

**Recording tool suggestions:** OBS Studio (free), ScreenToGif (lightweight),
or Windows Game Bar (Win+G).

---

## Appendix: Quick Reference

### All Commands

```bash
# WSL commands:
bash bin/hermes-pet start-all          # launch everything
bash bin/hermes-pet start-bridge        # bridge only
bash bin/hermes-pet status              # what's running
bash bin/hermes-pet doctor              # dependency check
bash bin/hermes-pet test                # run Python test suite
bash bin/hermes-pet test-event          # send fake event sequence
bash bin/hermes-pet test-event <state>  # send single state
bash bin/hermes-pet test-bridge         # one-shot DB check
bash bin/hermes-pet stop                # stop bridge
bash bin/hermes-pet stop-all            # stop everything

# Windows commands (CMD/PowerShell):
bin\hermes-pet.bat start-all
bin\hermes-pet.ps1 start-all
HermesPet.exe                           # start overlay with bridge
HermesPet.exe --no-bridge               # overlay only
HermesPet.exe --port 5731               # custom port
dotnet run -- --port 5731               # from source
```

### All Pet States

```
idle           — No activity, waiting
listening      — User just spoke, agent received message
thinking       — LLM API call in progress
tool_running   — Tool executing (bash, read_file, search_files, etc.)
waiting_for_jack — Agent waiting for user input
done           — Turn completed successfully
error          — Turn failed
unknown        — Startup, bridge disconnect, or DB error
```

### Event Protocol (Wire Format)

```json
{
  "event_type": "state_change",
  "state": "thinking",
  "timestamp": "2026-05-22T12:34:56.789Z",
  "payload": {
    "tool_name": null,
    "active_session_count": 2,
    "dominant_session_id": "s1",
    "_live_state_source": "live_state",
    "per_session": {
      "s1": "thinking",
      "s2": "tool_running"
    }
  }
}
```
