#!/usr/bin/env python
"""Run backend (uvicorn --reload) and frontend (Vite) together.

Cross-platform: works on native Windows, WSL2, and Linux. Ctrl+C stops both.
Usage: ``python scripts/dev.py`` (or ``make dev``).
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def _spawn(cmd: list[str], cwd: Path, name: str) -> subprocess.Popen:
    print(f"[dev] starting {name}: {' '.join(cmd)}")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # so Ctrl+C is isolated
    return subprocess.Popen(cmd, cwd=str(cwd), creationflags=creationflags)


def main() -> int:
    procs: list[tuple[str, subprocess.Popen]] = []

    backend_cmd = ["uv", "run", "python", "-m", "aicut", "serve", "--reload"]
    procs.append(("backend", _spawn(backend_cmd, ROOT, "backend (uvicorn)")))

    if (FRONTEND / "package.json").exists():
        if not (FRONTEND / "node_modules").exists():
            print("[dev] frontend/node_modules missing — running `npm install` first...")
            npm = "npm.cmd" if os.name == "nt" else "npm"
            subprocess.run([npm, "install"], cwd=str(FRONTEND), check=False)
        npm = "npm.cmd" if os.name == "nt" else "npm"
        procs.append(("frontend", _spawn([npm, "run", "dev"], FRONTEND, "frontend (vite)")))
    else:
        print("[dev] no frontend/package.json yet — backend only")

    print("\n[dev] backend:  http://127.0.0.1:8756")
    print("[dev] frontend: http://localhost:5173")
    print("[dev] press Ctrl+C to stop\n")

    try:
        while True:
            for name, p in procs:
                code = p.poll()
                if code is not None:
                    print(f"[dev] {name} exited with code {code}; shutting down")
                    raise KeyboardInterrupt
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for name, p in procs:
            if p.poll() is None:
                print(f"[dev] stopping {name}")
                try:
                    if os.name == "nt":
                        p.send_signal(signal.CTRL_BREAK_EVENT)
                    else:
                        p.terminate()
                except Exception:
                    p.kill()
        time.sleep(0.5)
        for _, p in procs:
            if p.poll() is None:
                p.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
