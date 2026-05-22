#!/usr/bin/env bash
# Hermes Pet Windows Overlay — Build and Run Helpers
# Usage:
#   bash pet.sh build           — Build the WPF overlay (requires .NET SDK on Windows)
#   bash pet.sh run             — Run the WPF overlay
#   bash pet.sh watcher         — Start the bridge watcher (WSL)
#   bash pet.sh test-bridge     — Run one-shot DB test
#   bash pet.sh test-fake       — Send fake events to overlay
#   bash pet.sh install-deps    — Install Python test deps (WSL)

set -euo pipefail
PROJECT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
OVERLAY_DIR="${PROJECT_DIR}/src/wpf/HermesPet"
BRIDGE_SCRIPT="${PROJECT_DIR}/src/bridge_watcher.py"
FAKE_SENDER="${PROJECT_DIR}/src/test_events.py"
STATE_DB="${HOME}/.hermes/profiles/phantom/state.db"
POST_URL="http://127.0.0.1:5731/event/"

case "${1:-help}" in
  build)
    echo "=== Building WPF Overlay ==="
    echo "This requires .NET 8 SDK on Windows."
    echo "Run from Windows (not WSL):"
    echo "  cd ${OVERLAY_DIR}"
    echo "  dotnet build -c Release"
    echo "  dotnet publish -c Release -r win-x64 --self-contained -o dist/"
    echo ""
    echo "Or from WSL:"
    echo "  cd ${OVERLAY_DIR}"
    echo "  dotnet build 2>/dev/null || echo 'Install .NET SDK or build on Windows'"
    ;;

  run)
    echo "=== Running WPF Overlay ==="
    echo "This runs on Windows. From PowerShell/CMD:"
    echo "  ${OVERLAY_DIR}\\bin\\Debug\\net8.0-windows\\HermesPet.exe --port 5731"
    echo ""
    echo "Or from WSL (after copy):"
    echo "  cd ${OVERLAY_DIR} && dotnet run -- --port 5731"
    ;;

  watcher)
    echo "=== Starting Bridge Watcher ==="
    echo "Watching: ${STATE_DB}"
    echo "Posting to: ${POST_URL}"
    echo ""
    echo "Run: python3 ${BRIDGE_SCRIPT} --db-path ${STATE_DB} --overlay-url ${POST_URL}"
    echo "For one-shot test: add --one-shot"
    echo ""
    # Actually start if DB exists
    if [ -f "${STATE_DB}" ]; then
      exec python3 "${BRIDGE_SCRIPT}" \
        --db-path "${STATE_DB}" \
        --overlay-url "${POST_URL}" \
        --poll-interval 1.0
    else
      echo "Warning: ${STATE_DB} not found"
      echo "Start anyway? Use: --db-path /path/to/state.db"
    fi
    ;;

  test-bridge)
    echo "=== One-shot Bridge Test ==="
    if [ -f "${STATE_DB}" ]; then
      python3 "${BRIDGE_SCRIPT}" \
        --db-path "${STATE_DB}" \
        --overlay-url "${POST_URL}" \
        --one-shot
    else
      echo "state.db not found at ${STATE_DB}"
      echo "Create a test DB or specify --db-path"
    fi
    ;;

  test-fake)
    echo "=== Sending Fake Events ==="
    echo "Sending to: ${POST_URL}"
    echo "Make sure the overlay is running first!"
    echo ""
    python3 "${FAKE_SENDER}" --url "${POST_URL}" --delay 1.5
    ;;

  test)
    echo "=== Running Tests ==="
    cd "${PROJECT_DIR}"
    python3 -m pytest tests/ -v
    ;;

  install-deps)
    echo "=== Installing Python Dependencies ==="
    pip install --break-system-packages pytest 2>/dev/null || pip install pytest
    ;;

  help|*)
    echo "Hermes Pet — Build and Run Script"
    echo ""
    echo "Commands:"
    echo "  build           Build the WPF overlay"
    echo "  run             Run the WPF overlay (Windows)"
    echo "  watcher         Start the bridge watcher (WSL)"
    echo "  test-bridge     One-shot DB state check"
    echo "  test-fake       Send fake events to overlay"
    echo "  test            Run all Python tests"
    echo "  install-deps    Install test dependencies"
    echo "  help            This help"
    ;;
esac
