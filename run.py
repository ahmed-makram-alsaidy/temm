"""Unified Runtime Launcher for AI Fleet OS."""

import os
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def parse_port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("AI_FLEET_PORT must be between 1 and 65535.")
    return port


def open_when_ready(url: str, timeout_seconds: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status == 200:
                    webbrowser.open(url)
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def main() -> None:
    host = os.environ.get("AI_FLEET_HOST", "127.0.0.1")
    port = parse_port(os.environ.get("AI_FLEET_PORT", "8787"))
    browser_host = "localhost" if host in {"127.0.0.1", "0.0.0.0", "::1"} else host
    url = f"http://{browser_host}:{port}"

    print("\n=======================================================")
    print("  TEMM — The Completion Runtime")
    print(f"  Starting server at {url}")
    print("=======================================================\n")

    if os.environ.get("AI_FLEET_NO_BROWSER", "").lower() not in {"1", "true", "yes"}:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    uvicorn.run("core.ai_fleet.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
