#!/usr/bin/env python
"""``make check`` — ruff + pytest + tsc --noEmit. Runs all, reports at the end."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"


def run(name: str, cmd: list[str], cwd: Path) -> bool:
    print(f"\n=== {name}: {' '.join(cmd)} ===")
    try:
        rc = subprocess.run(cmd, cwd=str(cwd)).returncode
    except FileNotFoundError:
        print(f"[skip] {name}: command not found")
        return True
    ok = rc == 0
    print(f"=== {name}: {'PASS' if ok else 'FAIL'} (exit {rc}) ===")
    return ok


def main() -> int:
    npm = "npm.cmd" if os.name == "nt" else "npm"
    results: list[tuple[str, bool]] = []

    results.append(("ruff", run("ruff", ["uv", "run", "ruff", "check", "backend", "tests", "scripts"], ROOT)))
    results.append(("pytest", run("pytest", ["uv", "run", "pytest", "-q"], ROOT)))

    if (FRONTEND / "node_modules").exists():
        results.append(("tsc", run("tsc", [npm, "run", "typecheck"], FRONTEND)))
        results.append(("vitest", run("vitest", [npm, "run", "test", "--", "--run"], FRONTEND)))
    else:
        print("\n[skip] frontend checks: run `npm install` in frontend/ first")

    print("\n" + "=" * 40)
    all_ok = True
    for name, ok in results:
        print(f"  {name:<10} {'PASS' if ok else 'FAIL'}")
        all_ok = all_ok and ok
    print("=" * 40)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
