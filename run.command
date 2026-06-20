#!/usr/bin/env bash
# PromptChain launcher for macOS. Double-click this file in Finder to start.
# First time only: if macOS blocks it, right-click the file and choose "Open".
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
    python3 run.py
else
    echo "Python 3.10+ is required but was not found."
    echo "Install it from https://www.python.org/downloads/ and try again."
    read -n 1 -s -r -p "Press any key to close..."
fi
