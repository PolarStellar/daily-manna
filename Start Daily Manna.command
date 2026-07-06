#!/bin/bash
# Double-click this to start the Daily Manna Studio server (the Generate button).
# Keep the window open while you use the app; close it to stop the server.
# First run may ask to allow Terminal access to your Documents folder — click OK.
cd "$(dirname "$0")" || exit 1
echo "Starting Daily Manna Studio…"
# Make sure phone access (Tailscale) is wired up — safe to run every time.
tailscale up 2>/dev/null
tailscale serve --bg --https=8790 localhost:8790 2>/dev/null && echo "Phone access ready (Tailscale)."
echo "Open http://localhost:8790 on this Mac, or"
echo "https://kriss-macbook-pro.taila0e65f.ts.net:8790 on your phone."
echo "(Keep this window open. Close it to stop.)"
echo
exec python3 studio/serve.py
