# Hermes Pet — Troubleshooting Guide

**Version:** 1.0 (public release)
**Date:** 2026-05-22

This guide covers common issues you may encounter when running Hermes Pet, their likely root causes, and step-by-step solutions.

---

## Table of Contents

1. [Overlay window doesn't appear or is invisible](#1-overlay-window-doesnt-appear-or-is-invisible)
2. [Pet stays idle / doesn't react to Hermes turns](#2-pet-stays-idle--doesnt-react-to-hermes-turns)
3. [Overlay not reachable in bridge logs](#3-overlay-not-reachable-in-bridge-logs)
4. [WSL bridge fails to start](#4-wsl-bridge-fails-to-start)
5. [state.db not found](#5-statedb-not-found)
6. [Pet shows unknown state](#6-pet-shows-unknown-state)
7. [Multiple Hermes sessions cause confusing state](#7-multiple-hermes-sessions-cause-confusing-state)
8. [Build errors (missing .NET SDK, wrong framework)](#8-build-errors-missing-net-sdk-wrong-framework)
9. [Port 5731 already in use](#9-port-5731-already-in-use)
10. [Windows antivirus blocking HermesPet.exe](#10-windows-antivirus-blocking-hermespetexe)
11. [WSL2 network changes (VPN, Docker, Hyper-V)](#11-wsl2-network-changes-vpn-docker-hyper-v)
12. [State looks stuck (thinking for too long)](#12-state-looks-stuck-thinking-for-too-long)

---

## 1. Overlay window doesn't appear or is invisible

### Symptom

- `hermes-pet status` shows the overlay process is running, but no window is visible on the desktop.
- `hermes-pet start-overlay` prints "MainWindowHandle is 0 — window may be invisible."

### Possible Causes

1. **Process started but window not yet shown.** The overlay uses a named mutex (`HermesPet-Overlay`) for single-instance enforcement. If a previous instance crashed silently, the mutex may still be held, blocking the new instance from creating its window.

2. **Window is off-screen.** If you previously moved the window to a secondary monitor that is no longer connected, WPF may restore the window off the visible desktop area.

3. **Started from a context where WPF cannot render.** Running HermesPet.exe from a non-interactive session (e.g., SSH, scheduled task) or as a different user will start the process but no window will be visible.

### Solutions

**Force reset the singleton mutex:**
```powershell
# From Windows PowerShell (admin)
Get-Process -Name HermesPet -ErrorAction SilentlyContinue | Stop-Process -Force
# Wait a moment, then start again
```

**Check for off-screen window:**
- Press `Win + Shift + Right Arrow` while the overlay is focused to move it to another monitor.
- Or use `hermes-pet.ps1 start-overlay` which includes position recovery logic.

**Verify interactive session:**
- The overlay must be launched from an interactive Windows desktop session (not via SSH, WinRM, or a scheduled task).
- Use `bin/hermes-pet.bat start-all` from a regular Command Prompt or PowerShell window.

---

## 2. Pet stays idle / doesn't react to Hermes turns

### Symptom

- Hermes Agent is actively working (you see responses in your terminal), but the overlay stays on `idle`.
- Bridge logs show only `→ idle (timeout)` cycles with no state transitions.

### Possible Causes

1. **Live-state columns missing.** If your Hermes Agent version doesn't write `live_state` columns, the bridge falls back to transcript inference. If the DB path is correct but inference thresholds aren't being met, the pet will stay idle.

2. **Wrong Hermes profile.** The bridge defaults to watching the `phantom` profile at `~/.hermes/profiles/phantom/state.db`. If you are running Hermes Agent under a different profile name, the bridge will watch the wrong database.

3. **State cursor is stuck.** The bridge tracks its position via `last_seen_id` in `src/bridge_watcher_state.json`. If this file becomes corrupted or has a stale cursor, the bridge may skip new messages.

4. **Overlay URL mismatch.** The bridge is sending events to the wrong IP or port, so the overlay never receives them.

### Solutions

**Run the doctor command to diagnose:**
```bash
bash bin/hermes-pet doctor
```
1. **Live-state columns missing.** If your Hermes Agent doesn't have [PR #30247](https://github.com/NousResearch/hermes-agent/pull/30247) applied, no `live_state` columns exist in the database. The bridge falls back to transcript inference, which cannot reliably show `tool_running` or `listening`. If the DB path is correct but inference thresholds aren't being met, the pet will stay idle.

   **Check with doctor:**
   ```bash
   bash bin/hermes-pet doctor
   ```
   Look for "live_state: columns MISSING" or "live_state: columns present". If missing, the pet will work in fallback mode only.
   
   **Check manually:**
   ```bash
   sqlite3 ~/.hermes/profiles/phantom/state.db \
     "PRAGMA table_info(sessions);" | grep live_state
   ```
   If no `live_state` columns exist, the bridge will use transcript inference exclusively. See [issue #12](#12-state-looks-stuck-thinking-for-too-long) for timeout tuning.

**Reset the bridge cursor:**
```bash
# Stop the bridge, delete cursor state, restart
bash bin/hermes-pet stop-bridge
rm -f src/bridge_watcher_state.json
bash bin/hermes-pet start-bridge
```

**Verify the correct profile path:**
```bash
bash bin/hermes-pet test-bridge --db-path ~/.hermes/profiles/<your-profile>/state.db
```

---

## 3. "Overlay not reachable" in bridge logs

### Symptom

Bridge log lines contain `(overlay not reachable)` after the state name, e.g.:
```
  → thinking [session=thinking] (overlay not reachable)
```

### Possible Causes

1. **Windows firewall blocking port 5731.** First launch of `HermesPet.exe` triggers a Windows Defender Firewall prompt. If denied, traffic from WSL is blocked.

2. **Overlay is not running.** The bridge starts and polls the database but cannot send events because the overlay process is not listening.

3. **WSL2 network isolation.** WSL2 has its own virtual network adapter. The bridge uses `ip route show default | awk '{print $3}'` to discover the Windows host IP. If this command fails or returns a wrong address, HTTP POSTs go nowhere.

4. **VPN or corporate network policy.** Some VPNs (NordVPN, Cisco AnyConnect, corporate proxies) add firewall rules or routing changes that block inter-VM traffic.

### Solutions

**Restart both components in order:**
```bash
bash bin/hermes-pet stop-all
bash bin/hermes-pet start-all
```

**Test basic reachability:**
```bash
# From WSL, detect the Windows host IP
WINDOWS_HOST=$(ip route show default | awk '{print $3}')
echo "Windows host: $WINDOWS_HOST"

# Test raw TCP connectivity
curl -s --max-time 2 \
  -X POST http://${WINDOWS_HOST}:5731/event/ \
  -H "Content-Type: application/json" \
  -d '{"event_type":"heartbeat","state":"idle"}' && echo " OK" || echo " FAIL"
```

**Check Windows firewall:**
```powershell
# From Windows PowerShell (admin)
netsh advfirewall firewall show rule name=all | findstr "5731"
# If no rule exists, add one for TCP 5731 on all profiles:
New-NetFirewallRule -DisplayName "Hermes Pet Port 5731" `
  -Direction Inbound -Protocol TCP -LocalPort 5731 -Action Allow
```

**Bypass VPN issues:**
- Add a static route or disable the VPN temporarily to test.
- Some VPNs offer a split-tunnel setting that allows local network traffic.
- As a last resort, use `--bridge-in-windows` mode (run `bridge_watcher.py` from Windows Python directly).

---

## 4. WSL bridge fails to start

### Symptom

- `hermes-pet start-bridge` reports failure or the bridge process exits immediately.
- `BridgeSupervisor` in the overlay shows status `BridgeExited` or `WslUnavailable`.
- Logs in `logs/bridge.log` are empty or contain a Python traceback.

### Possible Causes

1. **WSL2 is not installed or not running.** `wsl.exe` is not found, or no default Linux distribution is installed.

2. **Python 3 not available inside WSL.** The bridge is a Python script; if `python3` is not in the WSL PATH, launching it fails.

3. **Missing Python dependencies.** `bridge_watcher.py` imports `event_schema` and `state_mapper` from the same directory. If the working directory is wrong, imports fail.

4. **Permission denied on state.db.** The WSL user may not have read access to `~/.hermes/profiles/phantom/state.db`.

5. **Bridge is already running.** A stale PID file in `runtime/bridge.pid` points to a process that no longer exists, or a duplicate bridge is running.

### Solutions

**Check WSL availability from Windows:**
```powershell
# From Windows CMD/PowerShell
wsl.exe -l -v
wsl.exe bash -lc "python3 --version"
```

**Run the doctor command:**
```bash
bash bin/hermes-pet doctor
```

**Start the bridge manually in a WSL terminal** to see the error message:
```bash
cd $PROJECT_DIR
python3 src/bridge_watcher.py \
  --db-path ~/.hermes/profiles/phantom/state.db \
  --overlay-url http://$(ip route show default | awk '{print $3}'):5731/event/
```

**Clean up stale PID files:**
```bash
rm -f runtime/bridge.pid
bash bin/hermes-pet start-bridge
```

**Check Python availability:**
```bash
which python3
python3 --version
python3 -c "import sqlite3; import json; print('OK')"
```

---

## 5. state.db not found

### Symptom

- `hermes-pet doctor` reports `✗ state.db not found at ...`
- Bridge logs show `Error: DB not found at /home/user/.hermes/profiles/phantom/state.db`
- Overlay shows `DbMissing` status.

### Possible Causes

1. **Hermes Agent has never been run.** The `~/.hermes/` directory and its profile database are created on first launch of Hermes Agent. If you haven't used Hermes Agent yet, no `state.db` exists.

2. **Wrong profile name.** The bridge defaults to the `phantom` profile. If you configured Hermes Agent with a different profile name (e.g., `default`, `myprofile`), adjust the `--db-path` argument.

3. **Hermes Agent uses a different data directory.** The `~/.hermes` path is the default. If you set a custom `HERMES_DATA_DIR` or `XDG_DATA_HOME` environment variable, the database lives elsewhere.

4. **WSL path mismatch.** The hardcoded path in `BridgeSupervisor.cs` or the launcher scripts points to a different home directory than the actual WSL user.

### Solutions

**Locate the actual Hermes database:**
```bash
find ~ -name "state.db" 2>/dev/null
# or
find /home -name "state.db" 2>/dev/null
```

**Start Hermes Agent at least once** to create the database:
```bash
# In WSL
hermes-agent --profile phantom --message "Hello"
```
After the first message, `~/.hermes/profiles/phantom/state.db` will exist.

**Specify a custom DB path:**
```bash
# When starting the bridge manually:
python3 src/bridge_watcher.py --db-path /path/to/your/state.db

# Or via bin/hermes-pet, edit the script to set DB_PATH at the top.
```

**Check for Hermes environment variables:**
```bash
echo "HERMES_DATA_DIR=${HERMES_DATA_DIR:-unset}"
echo "XDG_DATA_HOME=${XDG_DATA_HOME:-unset}"
```

---

## 6. Pet shows "unknown" state

### Symptom

- The overlay displays `unknown` (gray color, question mark, "..." speech).
- Bridge logs show `→ unknown [db_error]` or similar.

### Possible Causes

1. **Database read error.** The bridge catches `StateDBError` (raised when SQLite queries fail) and emits an `unknown` state with reason `db_error`.

2. **Permission denied on state.db.** The bridge cannot open the database for reading.

3. **Database is locked or corrupt.** If another process (Hermes Agent itself, or a manual SQLite reader) has the database open in exclusive mode, the bridge may fail to read it.

4. **No event received for 15 seconds.** The overlay has a built-in connection timeout. If no events arrive from the bridge within 15 seconds, the display falls back to `unknown`.

### Solutions

**Check database accessibility:**
```bash
# From WSL
ls -la ~/.hermes/profiles/phantom/state.db
file ~/.hermes/profiles/phantom/state.db  # should say "SQLite 3.x database"
sqlite3 ~/.hermes/profiles/phantom/state.db "SELECT COUNT(*) FROM messages;"
```

**Restart both components:**
```bash
bash bin/hermes-pet stop-all
bash bin/hermes-pet start-all
```

**Check bridge logs for DB errors:**
```bash
bash bin/hermes-pet logs bridge 20
# Look for "DB error:" or "Error: Failed to query"
```

**Check if state.db is locked:**
```bash
# If sqlite3 returns "database is locked", wait a moment and retry.
# Hermes Agent writes synchronously; brief locks are normal.
```

---

## 7. Multiple Hermes sessions cause confusing state

### Symptom

- The overlay rapidly flickers between states (e.g., `thinking` ↔ `idle` cycling every second).
- The bridge log shows multiple sessions with conflicting states.
- The pet shows a state that doesn't match what Hermes is currently doing.

### Possible Causes

1. **Multiple active sessions.** Hermes Agent can have concurrent sessions (e.g., one in `thinking` for a new query, while an older session transitions to `done`). The bridge uses priority-based aggregation: `error > tool_running > thinking > waiting_for_jack > listening > done > idle`.

2. **An old session lingering in `thinking`.** If a session crashed or was interrupted, it may remain in the database with a recent timestamp but no active work, causing the bridge to show `thinking` when the agent is actually idle.

3. **Session-ended detection fighting with new messages.** The bridge's `has_session_just_ended()` check may fire `done` immediately before the next poll picks up new messages showing `thinking` again.

### Solutions

**View the per-session state distribution in DEBUG mode:**
- Right-click the overlay → "Switch to DEBUG Mode".
- Look for the `per_session` mapping in the status lines.

**Check bridge logs for session info:**
```bash
bash bin/hermes-pet logs bridge 50
# Lines show session IDs and states like:
#   → thinking [abc123=thinking, def456=done]
```

**End stale sessions in Hermes Agent:**
```bash
# Use Hermes API or simply start a new turn — old sessions may
# naturally expire after the idle threshold (10 seconds).
```

**Reset the bridge cursor** (clears session snapshot history):
```bash
bash bin/hermes-pet stop-bridge
rm -f src/bridge_watcher_state.json
bash bin/hermes-pet start-bridge
```

---

## 8. Build errors (missing .NET SDK, wrong framework)

### Symptom

- `dotnet build -c Release` fails with errors about missing SDK, unsupported framework, or `NETSDK1136`.
- The overlay .exe is not found at `src/wpf/HermesPet/bin/Release/net8.0-windows/win-x64/HermesPet.exe`.

### Possible Causes

1. **.NET 8 SDK not installed.** The project targets `net8.0-windows`. If you have .NET 6 or .NET 9 but not .NET 8, the build will fail.

2. **Built from WSL.** The WPF overlay requires native Windows UI tooling. `dotnet build` must run from **Windows** (PowerShell, CMD, or Developer Command Prompt), not from inside WSL.

3. **Missing Windows workload.** The .NET 8 SDK may be installed but missing the Windows desktop workload (`Microsoft.WindowsDesktop.App`).

4. **Wrong architecture.** The project configuration targets `win-x64`. Building on an ARM64 Windows system requires the x64 emulation layer or a modified project file.

### Solutions

**Check .NET SDK version (from Windows):**
```powershell
dotnet --list-sdks
dotnet --list-runtimes
# Look for "Microsoft.WindowsDesktop.App 8.x.x"
```

**Install or update .NET 8 SDK:**
- Download from: https://dotnet.microsoft.com/en-us/download/dotnet/8.0
- Ensure you include the "Desktop development with .NET" workload in the Visual Studio installer, or install the standalone SDK with WPF support.

**Build from Windows, not WSL:**
```powershell
# From Windows Command Prompt or PowerShell:
cd path\to\hermes-pet\src\wpf\HermesPet
dotnet build -c Release
```

**Verify build output:**
```powershell
if (Test-Path "bin\Release\net8.0-windows\win-x64\HermesPet.exe") {
    Write-Host "Build OK"
} else {
    Write-Host "Build output not found"
}
```

**Common error reference:**

| Error | Cause | Fix |
|-------|-------|-----|
| `NETSDK1136: The target framework 'net8.0-windows' was not found.` | .NET 8 SDK missing | Install .NET 8 SDK |
| `The specified framework version '8.0' could not be parsed` | VS Developer Console not used | Open "Developer Command Prompt for VS 2022" |
| `error MSB4019: The imported project "Wpf.props" was not found` | Windows workload missing | `dotnet workload install maui-windows` |
| `CSC: Source file 'MainWindow.xaml.cs' could not be found` | Wrong working directory | `cd` to the `.csproj` directory first |

---

## 9. Port 5731 already in use

### Symptom

- Overlay fails to start with a socket error.
- `hermes-pet doctor` shows port 5731 in use by another process.
- `Get-NetTCPConnection -LocalPort 5731` shows an existing `Listen` state.

### Possible Causes

1. **Another instance of HermesPet.exe is already running** (including a zombie process that didn't fully exit).

2. **Another application is using port 5731.** This is a relatively uncommon port, but some development tools, game servers, or proxy software may claim it.

3. **Stale socket from a previous crash.** The TCP socket may be in `TIME_WAIT` state, preventing a new listener on the same port.

### Solutions

**Find and stop the process using port 5731:**
```powershell
# From Windows PowerShell (admin)
$proc = Get-NetTCPConnection -LocalPort 5731 -ErrorAction SilentlyContinue |
  Select-Object -ExpandProperty OwningProcess
if ($proc) {
  Stop-Process -Id $proc -Force
  Write-Host "Killed process $proc"
}
```

**Use a different port:**
```powershell
# Start overlay on a different port
HermesPet.exe --port 5732

# Start bridge pointing to the new port
python3 src/bridge_watcher.py --overlay-url http://127.0.0.1:5732/event/
```

**Kill all Hermes Pet processes:**
```powershell
Get-Process -Name HermesPet -ErrorAction SilentlyContinue | Stop-Process -Force
```

**Wait for TIME_WAIT to clear:**
- If the port shows `TIME_WAIT`, wait 30–60 seconds and retry, or use a different port immediately.

---

## 10. Windows antivirus blocking HermesPet.exe

### Symptom

- `HermesPet.exe` is immediately deleted or quarantined after build or download.
- Windows SmartScreen shows "Windows protected your PC."
- The overlay process starts but is killed by real-time protection seconds later.

### Possible Causes

1. **Unsigned executable.** `HermesPet.exe` is built locally and has no Authenticode signature. Some antivirus engines flag unsigned .NET executables that use `TcpListener` (network listening) or `Process.Start` (process spawning) as suspicious.

2. **Heuristic false positive.** The `BridgeSupervisor` class launches `wsl.exe` as a child process, which antivirus software may interpret as suspicious behavior.

3. **Reputation-based detection.** Since the executable is new and not widely distributed, cloud-based reputation scoring (Windows Defender, SmartScreen) may block it.

### Solutions

**Add an exclusion in Windows Security:**
```powershell
# From PowerShell (admin)
Add-MpPreference -ExclusionPath "C:\path\to\hermes-pet"
```

Or manually:
1. Open **Windows Security** → **Virus & threat protection**
2. **Manage settings** → **Add or remove exclusions**
3. Add the `hermes-pet` directory (the entire project folder).

**Restore from quarantine if needed:**
```powershell
Get-MpThreatDetection | Where-Object Resources -like "*HermesPet*" | Restore-MpThreatDetection
```

**Build with a strong-name key** (optional):
```powershell
# Create a signing key (one time)
sn -k HermesPet.snk
# Then add <AssemblyOriginatorKeyFile>HermesPet.snk</AssemblyOriginatorKeyFile> to the .csproj
```

**Submit a false positive report** to Microsoft Security Intelligence if you believe the detection is incorrect.

---

## 11. WSL2 network changes (VPN, Docker, Hyper-V)

### Symptom

- Bridge starts but "overlay not reachable" appears after a VPN is connected.
- After waking from sleep, the pet stops updating.
- Docker Desktop or Hyper-V changes cause the bridge to lose connectivity.
- `ip route show default` returns an unexpected IP.

### Possible Causes

1. **WSL2 virtual switch resets.** WSL2's virtual network adapter can be reset when the host networking stack changes — VPN connect/disconnect, sleep/resume, Docker Desktop restart, Hyper-V configuration changes.

2. **VPN changes default gateway.** When a VPN connects, it may modify the routing table, changing the default gateway that `ip route show default | awk '{print $3}'` returns. This new gateway may not be the Windows host.

3. **Docker Desktop conflicts.** Docker Desktop also uses Hyper-V / WSL2 networking and may modify NAT rules or IP allocations that affect communication between WSL and Windows.

4. **Windows IP address changed.** If the Windows host gets a new IP (DHCP renewal, network switch, hotspot tethering), the bridge's overlay URL becomes stale.

### Solutions

**Restart the bridge after any network change:**
```bash
bash bin/hermes-pet restart-bridge
```
The bridge re-detects the Windows host IP on startup.

**Monitor the default gateway:**
```bash
# Run this periodically to see gateway changes
watch -n 2 'ip route show default | awk "{print \$3}"'
```

**Use localhost forwarding (WSL2 config):**
Create or edit `%USERPROFILE%\.wslconfig` on Windows:
```ini
[wsl2]
localhostForwarding=true
```
Then restart WSL:
```powershell
wsl.exe --shutdown
```
This allows you to use `127.0.0.1` from WSL to reach Windows services, bypassing gateway discovery.

**Run the bridge inside Windows directly** (no WSL dependency):
```powershell
# Install Python on Windows, then:
cd path\to\hermes-pet
python src\bridge_watcher.py --overlay-url http://127.0.0.1:5731/event/
```

**After sleep/resume:**
```bash
bash bin/hermes-pet stop-bridge
bash bin/hermes-pet start-bridge
```

---

## 12. State looks stuck (thinking for too long)

### Symptom

- The overlay shows `thinking` or `tool_running` for many seconds after Hermes has actually finished.
- The bridge log shows `→ thinking` without a subsequent transition to `done` or `idle`.
- The state seems frozen even though Hermes Agent is idle.

### Possible Causes

1. **Live-state timeout vs transcript staleness.** The bridge has two freshness windows:
   - **Live-state freshness:** 30 seconds (`LIVE_STATE_FRESHNESS_SECONDS` in `state_mapper.py`). If Hermes writes `live_state = thinking` and then stops writing (e.g., session completes), the bridge will keep showing `thinking` for up to 30 seconds before falling back to transcript inference.
   - **Transcript idle timeout:** 10 seconds (`DEFAULT_IDLE_THRESHOLD_SECONDS`). If no new messages appear in the database for 10 seconds, transcript-based state transitions to `idle`.

2. **Live-state writes but transcript doesn't advance.** Some Hermes Agent versions write `live_state` frequently (every poll cycle), keeping it fresh even when the agent is actually idle. The live-state freshness window (30s) is wider than the transcript idle threshold (10s), so live-state can dominate and appear stuck.

3. **Session ended but live_state still fresh.** If a session ends but the `live_state` columns were updated within the last 30 seconds, the bridge still considers them fresh and continues showing the previous state.

### Solutions

**Check which inference source is active (DEBUG mode):**
- Right-click overlay → "Switch to DEBUG Mode"
- Look for `live_state` or `transcript_fallback` in the status line.
- If `live_state` is shown, the bridge is using live-state columns directly.
- If `transcript_fallback`, it's using message timestamps.

**Force fallback by waiting:**
- If live-state is stuck, it will resolve after 30 seconds when the freshness window expires and the bridge falls back to transcript inference (which uses a 10-second idle threshold).

**Reset the bridge to clear stale state:**
```bash
bash bin/hermes-pet stop-bridge
rm -f src/bridge_watcher_state.json
bash bin/hermes-pet start-bridge
```

**Check live-state writes in the database:**
```bash
sqlite3 ~/.hermes/profiles/phantom/state.db \
  "SELECT id, live_state, live_state_updated_at, current_tool_name
   FROM sessions
   WHERE live_state IS NOT NULL
   ORDER BY live_state_updated_at DESC
   LIMIT 5;"
```
If you see rows with `live_state_updated_at` within the last 30 seconds but the session has ended, the bridge is correctly (but frustratingly) showing the live-state until it expires.

**Event flow timeline reference:**

| Time | Hermes Action | DB State | Bridge Shows |
|------|--------------|----------|-------------|
| T+0s | User sends message | `live_state=listening` | `listening` |
| T+1s | LLM API starts | `live_state=thinking` | `thinking` |
| T+5s | Turn completes | `live_state=done` | `done` |
| T+6s | No new messages | transcript: no new msgs >10s → `idle` | **`done` → `idle`** (fast) |
| T+6s | If live_state still fresh | live_state still shows `done` (<30s) | **`done`** (live-state dominates) |
| T+36s | Live-state expires (>30s) | fallback to transcript | **`idle`** |

If you frequently see stuck states, the live-state freshness window (30s) may be too long. This can be tuned in `state_mapper.py` by lowering `LIVE_STATE_FRESHNESS_SECONDS`.

---

## Diagnostic Toolkit

Run these commands in order when troubleshooting:

```bash
# 1. Full health check
bash bin/hermes-pet doctor

# 2. View recent bridge logs
bash bin/hermes-pet logs bridge 50

# 3. Send a test event to verify end-to-end connectivity
bash bin/hermes-pet test-event thinking

# 4. One-shot database state check
bash bin/hermes-pet test-bridge

# 5. Run Python test suite
bash bin/hermes-pet test
```

### Log Files Reference

| Log | Location | Contents |
|-----|----------|----------|
| Bridge watcher | `logs/bridge.log` | State transitions, DB errors, overlay reachability |
| Bridge supervisor | `logs/bridge_supervisor.log` | WSL bridge process lifecycle (Windows side) |
| Bridge state | `src/bridge_watcher_state.json` | Cursor position, last state, session snapshot |

---

## Architecture Reference

```
WSL2 (Ubuntu)                          Windows 11
┌──────────────────┐      HTTP       ┌──────────────────┐
│  Hermes Agent     │    POST :5731   │  HermesPet.exe   │
│  (phantom profile)│ ──────────────▶│  (WPF Overlay)   │
│  state.db         │                 │                  │
│       ▲           │                 │  PET mode (sprite)│
│       │ poll 1s   │                 │  DEBUG mode (text)│
│  bridge_watcher.py│                 │                  │
└──────────────────┘                 └──────────────────┘
```

For a complete system description, see `docs/architecture.md`.

---

## Still Having Trouble?

If none of the solutions above resolve your issue:

1. Capture logs:
   ```bash
   bash bin/hermes-pet logs bridge 200 > /tmp/hermes-pet-bridge.log
   ```
2. Run the doctor and save output:
   ```bash
   bash bin/hermes-pet doctor > /tmp/hermes-pet-doctor.log
   ```
3. Check the events sent/received by running the overlay in `--no-bridge` mode and manually sending test events.

Common misconfiguration: **building from WSL instead of Windows**, or **running the overlay from a non-interactive session**. Double-check these first.
