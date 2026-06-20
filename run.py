"""
PromptChain — One-click launcher

Lets a user start the app without touching a terminal. Double-click run.bat
(Windows), run.command (macOS), or run.sh (Linux) and this script:

  1. creates a self-contained virtual environment on first run,
  2. installs the dependencies into it (first run only),
  3. starts the Streamlit server, and
  4. opens PromptChain in the default browser.

It uses only the Python standard library, so it can bootstrap everything else.
"""

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
PREFERRED_PORT = 8501


def _venv_python() -> Path:
    """Path to the Python interpreter inside the project venv."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(cmd, fatal: bool = True) -> int:
    """Run a command, streaming its output. Exit on failure when fatal."""
    print(">", " ".join(str(c) for c in cmd))
    code = subprocess.call(cmd)
    if code != 0 and fatal:
        sys.exit(f"Command failed (exit {code}): {' '.join(str(c) for c in cmd)}")
    return code


def ensure_environment() -> Path:
    """Create the venv and install requirements when needed. Returns the path
    to the venv's Python interpreter."""
    py = _venv_python()

    if not py.exists():
        print("Setting up a local environment (first run only)...")
        _run([sys.executable, "-m", "venv", str(VENV_DIR)])

    # Only install when Streamlit isn't already present in the venv, so later
    # launches start instantly.
    streamlit_present = subprocess.call(
        [str(py), "-c", "import streamlit"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) == 0

    if not streamlit_present:
        print("Installing dependencies (this can take a minute)...")
        _run([str(py), "-m", "pip", "install", "--upgrade", "pip"], fatal=False)
        _run([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    return py


def find_port(preferred: int) -> int:
    """Return the preferred port if free, otherwise an OS-assigned free one."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_until_up(port: int, timeout: float = 60.0) -> bool:
    """Poll the server until it accepts connections or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def main() -> None:
    os.chdir(ROOT)
    py = ensure_environment()
    port = find_port(PREFERRED_PORT)
    url = f"http://localhost:{port}"

    print(f"\nStarting PromptChain at {url}")
    print("Keep this window open while you use the app; close it to quit.\n")

    proc = subprocess.Popen([
        str(py), "-m", "streamlit", "run", "app.py",
        "--server.port", str(port),
        "--server.headless", "true",
    ])

    try:
        if wait_until_up(port):
            webbrowser.open(url)
        else:
            print(f"Server is taking longer than expected — open {url} manually.")
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if proc.poll() is None:
            proc.terminate()


if __name__ == "__main__":
    main()
