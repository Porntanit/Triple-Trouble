#!/bin/bash
# Start from the extracted folder, even when its name contains spaces.
cd -- "$(dirname -- "$0")" || exit 1
chosen_python=""
for candidate in python3.12 python3.11 python3.10 python3.13 python3 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12 /Library/Frameworks/Python.framework/Versions/3.12/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(not ((3,10) <= sys.version_info[:2] < (3,14)))' >/dev/null 2>&1; then
    chosen_python="$candidate"
    break
  fi
done
if [ -z "$chosen_python" ]; then
  echo "Please install Python 3.12 for macOS first (Python 3.10–3.13 is supported)."
  echo "Download: https://www.python.org/downloads/macos/"
  echo "Then double-click Start-on-Mac.command again."
  read -r -p "Press Enter to close… "
  exit 1
fi
"$chosen_python" launch.py
launch_status=$?
if [ "$launch_status" -ne 0 ]; then
  echo "See START-HERE-TH.md for setup and troubleshooting."
  read -r -p "Press Enter to close… "
fi
exit "$launch_status"
