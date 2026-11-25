#!/bin/bash
# Double-click this file to start Clinora AI, then open http://localhost:8765
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up (one time)..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
( sleep 2; open "http://localhost:8765" ) &
.venv/bin/python server.py
