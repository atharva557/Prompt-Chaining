#!/usr/bin/env bash
# PromptChain launcher for Linux. Run ./run.sh (or double-click if your file
# manager is set to run executables) to start the app.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    python3 run.py
else
    echo "Python 3.10+ is required but was not found."
    echo "Install it with your package manager (e.g. sudo apt install python3 python3-venv)."
fi
