#!/bin/bash
set -e

# Start Xvfb (virtual display for Chrome)
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99

# CAPTCHA service URL (máquina Windows via ngrok)
# Atualizar quando a URL do ngrok mudar
export CAPTCHA_SERVICE_URL="${CAPTCHA_SERVICE_URL:-}"

# Wait for Xvfb
sleep 1

# Start Python RPA worker in background
cd /app/worker
python3 rpa_worker.py &
WORKER_PID=$!
cd /app

# Wait for worker to be ready
for i in $(seq 1 10); do
    if curl -s http://127.0.0.1:8787/health > /dev/null 2>&1; then
        echo "Worker ready!"
        break
    fi
    sleep 1
done

# Start Node.js server (foreground)
exec node server.js
