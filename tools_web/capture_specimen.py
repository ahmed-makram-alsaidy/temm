"""Capture the V1 token specimen (dev-only proof surface) for visual review.

usage:  python tools_web/capture_specimen.py
"""
import os
import socket
import subprocess
import tempfile
import threading
import shutil
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

WEB = Path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apps", "web")
WEB = os.path.abspath(WEB)
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "specimen")
OUT = os.path.abspath(OUT)
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# name, w, h, fragment-query
SHOTS = [
    ("specimen-graphite",  1440, 1250, ""),
    ("specimen-chalk",     1440, 1250, "&canvas=chalk"),
    ("specimen-rtl",       1440, 1250, "&rtl=1"),
    ("specimen-greyscale", 1440, 1250, "&grey=1"),
    ("specimen-reduced",   1440, 1250, "&reduced=1"),
]


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Q(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=WEB, **k)
    def log_message(self, *a): pass


def main():
    os.makedirs(OUT, exist_ok=True)
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Q)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}/specimen/index.html"
    print(f"serving {WEB}\n  {base}")

    ok = fail = 0
    for name, w, h, q in SHOTS:
        path = os.path.join(OUT, name + ".png")
        profile = tempfile.mkdtemp(prefix="temm-spec-")
        cmd = [
            CHROME, "--headless=new", f"--screenshot={path}",
            f"--window-size={w},{h}", "--force-device-scale-factor=2",
            f"--user-data-dir={profile}",
            "--hide-scrollbars", "--disable-gpu", "--no-first-run",
            "--force-color-profile=srgb", "--font-render-hinting=none",
            "--virtual-time-budget=6000",
            f"{base}?shot=1{q}",
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        shutil.rmtree(profile, ignore_errors=True)
        if os.path.exists(path):
            print(f"  ok   {name:22s} {os.path.getsize(path)/1024:8.1f} KB")
            ok += 1
        else:
            print(f"  FAIL {name}: {r.stderr.decode(errors='replace')[-200:]}")
            fail += 1
    srv.shutdown()
    print(f"\n{ok} captured -> {OUT}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
