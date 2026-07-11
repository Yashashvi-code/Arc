#!/bin/bash
ARC_DIR="$HOME/Arc"
VENV_PYTHON="$ARC_DIR/.venv/bin/python3"
DAEMON="$ARC_DIR/daemon/src/main.py"
PANEL="/mnt/extra/arc-panel/AppRun"

echo "[ ARC ] Starting..."
"$VENV_PYTHON" "$DAEMON" &
DAEMON_PID=$!
sleep 3
"$PANEL" &
PANEL_PID=$!

echo "[ ARC ] Running. Ctrl+C to stop everything."
trap "echo '[ ARC ] Shutting down...'; kill $DAEMON_PID $PANEL_PID 2>/dev/null; exit 0" SIGINT SIGTERM
wait
