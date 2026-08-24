#!/bin/bash
# Move to the directory containing this script
cd "$(dirname "$0")"

echo "========================================================="
echo " 🔥 Starting FloodBot v3.0 Automation Suite on macOS... "
echo "========================================================="

# Ensure virtual environment is ready
if [ ! -d ".venv" ]; then
    echo "❌ Python virtual environment (.venv) not found!"
    echo "Creating virtual environment and installing dependencies..."
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
fi

# Ensure local binary tools (ffmpeg, yt-dlp) are ready
echo "🔍 Checking binary dependencies (ffmpeg, yt-dlp)..."
.venv/bin/python3 download_binaries.py

# Automatically open the browser tab once the app starts
(sleep 2 && open "http://127.0.0.1:8080") &

# Start the Flask web app server
.venv/bin/python3 app.py
