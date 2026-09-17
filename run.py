"""
Single entry point to start the whole system, per the assessment's
'must start with a single command' constraint.

Launches the FastAPI backend and the Streamlit UI as two subprocesses,
waits for the API to become healthy before starting the UI (so the UI
doesn't show connection errors on first load), and shuts both down
cleanly on Ctrl+C.

Usage:
    python run.py
"""
import subprocess
import sys
import time
import signal
import requests

API_URL = "http://127.0.0.1:8000/health"


def wait_for_api(timeout=30):
    """Polls the API's health endpoint until it responds or we give up."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            if requests.get(API_URL, timeout=1).status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(0.5)
    return False


def main():
    print("Starting API (uvicorn)...")
    api_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"]
    )

    print("Waiting for the API to become healthy...")
    if not wait_for_api():
        print("API did not start in time. Shutting down.")
        api_process.terminate()
        sys.exit(1)
    print("API is healthy.")

    print("Starting UI (streamlit)...")
    ui_process = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "streamlit_app.py"]
    )

    def shutdown(signum, frame):
        print("\nShutting down...")
        ui_process.terminate()
        api_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    # Keep the script alive while both subprocesses run; if either one
    # exits on its own, bring the other down too instead of leaving an
    # orphaned process running in the background.
    while True:
        if api_process.poll() is not None or ui_process.poll() is not None:
            shutdown(None, None)
        time.sleep(1)


if __name__ == "__main__":
    main()