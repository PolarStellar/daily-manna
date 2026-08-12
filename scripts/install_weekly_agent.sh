#!/bin/bash
# Install (or remove) the launchd agent that generates the week's articles
# on its own whenever the Mac is up and Kris isn't in a Claude session.
#
#   ./scripts/install_weekly_agent.sh install [monday|daily]
#   ./scripts/install_weekly_agent.sh status
#   ./scripts/install_weekly_agent.sh uninstall
#
# The agent just runs scripts/generate_week.py, which gates and paces itself:
# it needs the Studio server up, backs off if a Claude session is open, skips
# days that already exist, and rests between days. So firing it often is cheap
# and safe — most passes do nothing and exit in under a second.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.polarstellar.daily-manna.week"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
ACTION="${1:-status}"
MODE="${2:-daily}"

write_plist() {
  local intervals=""
  local weekday_line=""
  if [ "$MODE" = "monday" ]; then
    weekday_line="      <key>Weekday</key><integer>1</integer>"
  fi
  for h in 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21; do
    intervals+="    <dict>
      <key>Hour</key><integer>$h</integer>
      <key>Minute</key><integer>5</integer>
$weekday_line
    </dict>
"
  done

  mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>$REPO/scripts/generate_week.py</string>
    <string>--gap</string><string>300</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartCalendarInterval</key>
  <array>
$intervals  </array>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$REPO/logs/launchd.out</string>
  <key>StandardErrorPath</key><string>$REPO/logs/launchd.err</string>
</dict>
</plist>
PLIST_EOF
}

case "$ACTION" in
  install)
    if [ "$MODE" != "monday" ] && [ "$MODE" != "daily" ]; then
      echo "mode must be 'monday' or 'daily'" >&2; exit 1
    fi
    write_plist
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$UID" "$PLIST"
    echo "installed: $LABEL ($MODE, hourly 7am-9pm)"
    echo "plist:     $PLIST"
    echo "log:       $REPO/logs/generate_week.log"
    ;;
  uninstall)
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed: $LABEL"
    ;;
  status)
    if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
      echo "loaded: $LABEL"
      launchctl print "gui/$UID/$LABEL" | grep -E "state|last exit|runs" || true
    else
      echo "not loaded: $LABEL"
    fi
    ;;
  *)
    echo "usage: $0 {install [monday|daily]|uninstall|status}" >&2; exit 1
    ;;
esac
