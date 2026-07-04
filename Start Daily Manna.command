#!/bin/bash
# Double-click this to start the Daily Manna Studio server (the Generate button).
# Keep the window open while you use the app; close it to stop the server.
# First run may ask to allow Terminal access to your Documents folder — click OK.
cd "$(dirname "$0")" || exit 1
echo "Starting Daily Manna Studio…"
echo "Open http://localhost:8790 in your browser."
echo "(Keep this window open. Close it to stop.)"
echo
exec python3 studio/serve.py
