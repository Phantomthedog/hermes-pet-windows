# Hermes Pet

A floating desktop companion that brings your [Hermes Agent](https://github.com/NousResearch/hermes-agent) to life on your Windows desktop.

Hermes Pet runs as a transparent always-on-top overlay that shows the agent's current state — listening, thinking, running tools, idle — through animated sprites or a debug status panel.

## How It Works

```
┌─ WSL (Linux) ─────────────────────────────────────┐
│  Hermes Agent (phantom profile)                   │
│       │ writes live_state to                       │
│       ▼                                            │
│  ~/.hermes/profiles/phantom/state.db               │
│       │ polled every 1s by                          │
│       ▼                                            │
│  bridge_watcher.py  ── HTTP POST ──┐                │
└────────────────────────────────────┘                │
                                                     ▼
┌─ Windows ───────────────────────────────────────────┐
│  HermesPet.exe (WPF overlay, port 5731)             │
│    ├─ PET mode: sprite animation per state          │
│    └─ DEBUG mode: text labels + state colors        │
└─────────────────────────────────────────────────────┘
```

### State Detection

Hermes Pet has **two detection modes**:

**Primary — Live-state (fast):** Hermes core writes `live_state` to the sessions table at each lifecycle stage — `listening` when your message arrives, `thinking` before the model API call, `tool_running` before a tool executes (with the tool name), and `done` or `error` when the turn finishes. The bridge reads this every second.

**Fallback — Transcript inference:** If live-state columns don't exist (Hermes Agent without [PR #30247](https://github.com/NousResearch/hermes-agent/pull/30247)) or the data is stale, the bridge falls back to inferring state from recent message timestamps and roles.

## Requirements

> **Important:** Hermes Pet works best with Hermes Agent live-state support.
> Live-state support is proposed upstream in [PR #30247](https://github.com/NousResearch/hermes-agent/pull/30247).
> Until that PR is merged and released, see the two modes below.

- **Windows 10/11** (for the WPF overlay)
- **WSL2** with Ubuntu (for the Python bridge watcher)
- **Hermes Agent** running in WSL (any profile — default is `phantom`)
- **.NET 8 SDK** on Windows (to build the overlay)
- **Python 3** in WSL (for the bridge watcher — normally already present)

### Hermes live-state modes

**Fallback mode (no Hermes core patch required)**
The pet infers broad states from transcript rows. `tool_running` and `listening` may be delayed or unreliable.

**Live-state mode (recommended — requires PR #30247)**
Apply the live-state patch from [PR #30247](https://github.com/NousResearch/hermes-agent/pull/30247) to your Hermes Agent checkout. Enables real-time states:
`listening → thinking → tool_running → done`

Run `bash bin/hermes-pet doctor` to check whether your Hermes state.db has live-state columns.

## Quick Start

### 1. Build the Overlay

From Windows (PowerShell or CMD):

```powershell
cd src\wpf\HermesPet
dotnet build -c Release
```

### 2. Run

The easiest way — starts both the overlay and the bridge watcher:

```powershell
# From Windows (CMD):
bin\hermes-pet.bat start-all

# Or from WSL:
bash bin/hermes-pet start-all
```

Or run the overlay standalone (bridge must be started separately):

```powershell
# Windows:
cd src\wpf\HermesPet\bin\Release\net8.0-windows\win-x64
HermesPet.exe                  # auto-starts WSL bridge
HermesPet.exe --no-bridge      # manual bridge mode
dotnet run -- --port 5731      # from source
```

### 3. Test

```bash
# Python tests (WSL):
bash bin/hermes-pet test       # or: uv run --with pytest python -m pytest tests/

# Send a fake state event to the overlay:
bash bin/hermes-pet test-event thinking

# One-shot DB check:
bash bin/hermes-pet test-bridge

# Health check:
bash bin/hermes-pet doctor
```

### 4. Controls

- **Right-click** the overlay → context menu (switch PET/DEBUG mode, reload assets, exit)
- **Left-click drag** to move the window
- **DEBUG mode**: shows state label, message preview, session count, live-state source

## Files

```
src/
  bridge_watcher.py        Main polling loop (WSL)
  state_mapper.py          DB query → state inference
  event_schema.py          Event validation
  test_events.py           Fake event sender
  wpf/HermesPet/
    Program.cs             Entry point
    MainWindow.xaml(.cs)   Dual-mode overlay window
    PetEngine.cs           State → display mapping
    EventReceiver.cs       HTTP event listener
    BridgeSupervisor.cs    WSL bridge process manager
    PetAssetManager.cs     Sprite sheet loader
    HermesPet.csproj       .NET 8 WPF project
assets/pets/
  border-collie-v2/         Default pet sprite set (see ATTRIBUTIONS)
tests/
  test_event_schema.py     Event validation
  test_state_mapper.py     State inference
  test_bridge_watcher.py   Bridge integration
  test_live_state.py       Live-state lifecycle
  test_event_protocol.py   Send/receive
  test_multi_session.py    Multi-session
bin/
  hermes-pet               Shell control wrapper (WSL)
  hermes-pet.bat           Batch launcher (Windows)
  hermes-pet.ps1           PowerShell launcher (Windows)
  create-desktop-shortcut.ps1
```

## Live-State Contract (Hermes Core)

> **Requires Hermes Agent live-state support.** At the time of writing this is proposed upstream in [PR #30247](https://github.com/NousResearch/hermes-agent/pull/30247). Apply the patch to enable live-state columns.

The `sessions` table includes four optional columns for live execution state:

| Column | Type | Description |
|---|---|---|
| `live_state` | TEXT | Current state: listening, thinking, tool_running, waiting_for_jack, done, error, idle, unknown |
| `live_state_updated_at` | REAL | Unix timestamp of last state change |
| `current_tool_name` | TEXT | Name of the tool currently executing (or None) |
| `live_state_detail` | TEXT | Optional detail (e.g. error message) |

The columns are **nullable** and **backward-compatible** — existing databases without them continue to work, with the bridge falling back to transcript-based inference.

### Lifecycle

```
User sends message  →  live_state = listening
     ↓
Model API called    →  live_state = thinking
     ↓
Tool executes       →  live_state = tool_running  (current_tool_name = tool name)
     ↓
Model API called    →  live_state = thinking  (next iteration)
     ↓
Turn completes      →  live_state = done
     ↓
Idle                →  live_state = idle  (after freshness window)
```

## Configuration

The bridge and overlay accept command-line arguments:

```bash
# Bridge:
python3 src/bridge_watcher.py \
    --db-path "/path/to/state.db" \
    --overlay-url "http://127.0.0.1:5731/event/" \
    --poll-interval 1.0 \
    --heartbeat-interval 5.0 \
    --one-shot

# Overlay:
HermesPet.exe --port 5731 --no-bridge
```

## Event Protocol

See `docs/event_protocol_draft.md` for the full JSON event schema.

States: `idle`, `listening`, `thinking`, `tool_running`, `waiting_for_jack`, `done`, `error`, `unknown`

Event types: `state_change`, `message_chunk`, `tool_start`, `tool_result`, `error_occurred`, `heartbeat`, `reset`

## Project Status

**Active development.** Current features:
- Live-state tracking (real-time listening/thinking/tool_running detection)
- Multi-session aggregation
- Dual PET/DEBUG modes
- One-EXE supervisor (auto-starts WSL bridge)
- Remote bridge management from Windows
- Selectable pet themes

**Known limitations:**
- Watches a single Hermes profile by default (configurable)
- 1-second polling latency
- No streaming content — only sees completed messages
- No autostart service (Task Scheduler or systemd)
- PET mode requires a sprite set for each state

## License

The Hermes Pet codebase (Python, C#, scripts, build configuration) is licensed under the **MIT License** — see `LICENSE`.

**Third-party pet assets** in `assets/pets/` may have separate terms. The border-collie-v2 sprite set is a community-shared asset from Codex Pet Share, included for compatibility purposes. See `ATTRIBUTIONS.md` and `assets/pets/border-collie-v2/LICENSE-NOTE.md` for details.
