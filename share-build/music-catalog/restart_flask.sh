#!/bin/bash
# Restart the Flask music catalog app
cd "$(dirname "$0")"

echo "Stopping Flask..."
pkill -f "python3 app.py" 2>/dev/null
lsof -ti :5000 | xargs kill -9 2>/dev/null
sleep 1

echo "Starting Flask..."
nohup python3 app.py > flask.log 2>&1 &
echo "Flask started (PID $!) — listening on http://0.0.0.0:5000"
echo "Log: $(dirname "$0")/flask.log"
