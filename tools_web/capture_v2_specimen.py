"""Capture the V2 execution primitive specimen through the Vite dev server."""

from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
OUT = ROOT / "docs" / "specimen-v2"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# name, viewport width, viewport height, device scale, query
SHOTS = [
    ("v2-graphite-full", 1440, 5800, 1, ""),
    ("v2-chalk-full", 1440, 5800, 1, "theme=light"),
    ("v2-greyscale-full", 1440, 5800, 1, "grey=1"),
    ("v2-rtl-full", 1440, 5800, 1, "rtl=1"),
    ("v2-compact-mobile", 600, 1200, 2, "compact=1"),
    ("v2-closed-cell-sheet", 1200, 900, 2, "focus=cell"),
    ("v2-failure-comparison", 1200, 760, 2, "focus=failures&grey=1"),
    ("v2-attempt-history", 1200, 760, 2, "focus=attempt"),
    ("v2-reduced-motion", 1200, 900, 2, "focus=cell&reduced=1&motion=closed"),
    ("v2-high-contrast-status", 1200, 1100, 2, "focus=status"),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Vite exited before the specimen became available")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError("Timed out waiting for Vite")


def main() -> int:
    require_chrome = CHROME.exists()
    if not require_chrome:
        raise FileNotFoundError(f"Chrome not found: {CHROME}")

    OUT.mkdir(parents=True, exist_ok=True)
    port = free_port()
    base = f"http://127.0.0.1:{port}/specimen/v2.html"
    vite = subprocess.Popen(
        ["npm.cmd", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=WEB,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    failures = 0
    try:
        wait_for_server(base, vite)
        print(f"serving {base}")
        for name, width, height, scale, query in SHOTS:
            output = OUT / f"{name}.png"
            profile = Path(tempfile.mkdtemp(prefix="temm-v2-"))
            url = f"{base}?{query}" if query else base
            command = [
                str(CHROME),
                "--headless=new",
                f"--screenshot={output}",
                f"--window-size={width},{height}",
                f"--force-device-scale-factor={scale}",
                f"--user-data-dir={profile}",
                "--hide-scrollbars",
                "--disable-gpu",
                "--no-first-run",
                "--force-color-profile=srgb",
                "--font-render-hinting=none",
                "--virtual-time-budget=4000",
                url,
            ]
            if name == "v2-high-contrast-status":
                command.insert(-1, "--force-high-contrast")
            result = subprocess.run(command, capture_output=True, timeout=120)
            shutil.rmtree(profile, ignore_errors=True)
            if result.returncode == 0 and output.exists() and output.stat().st_size > 10_000:
                print(f"ok   {name:24s} {output.stat().st_size / 1024:8.1f} KB")
            else:
                failures += 1
                error = result.stderr.decode(errors="replace")[-240:]
                print(f"FAIL {name}: {error}")
    finally:
        vite.terminate()
        try:
            vite.wait(timeout=10)
        except subprocess.TimeoutExpired:
            vite.kill()

    print(f"{len(SHOTS) - failures} captured -> {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
