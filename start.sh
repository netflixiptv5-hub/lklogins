#!/bin/bash
set -e

# Start Xvfb (virtual display for Chrome)
echo "Starting Xvfb..."
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
export DISPLAY=:99

# CAPTCHA service URL (máquina Windows via ngrok)
export CAPTCHA_SERVICE_URL="${CAPTCHA_SERVICE_URL:-}"

# Wait for Xvfb and verify it's running
sleep 2
if ! kill -0 $XVFB_PID 2>/dev/null; then
    echo "WARNING: Xvfb failed to start! Will use headless mode."
    export XVFB_FAILED=1
else
    echo "Xvfb running on :99 (PID $XVFB_PID)"
fi

# Start Python RPA worker in background
cd /app/worker
python3 rpa_worker.py &
WORKER_PID=$!
cd /app

# Wait for worker to be ready
for i in $(seq 1 15); do
    if curl -s http://127.0.0.1:8787/health > /dev/null 2>&1; then
        echo "Worker ready!"
        break
    fi
    sleep 1
done

# Start Node.js server (foreground)
exec node server.js
