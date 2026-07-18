"""aicut CLI entry point: ``python -m aicut <command>``.

Commands:
    doctor   run environment diagnostics
    serve    start the FastAPI backend (uvicorn)
    version  print the version
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main(argv: list[str] | None = None) -> int:
    # Windows legacy consoles default to cp1252; force UTF-8 so nothing crashes
    # on non-ASCII output. Best-effort — never fatal.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            pass

    parser = argparse.ArgumentParser(prog="aicut", description="AI-controlled video editor")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("doctor", help="check the environment")
    sub.add_parser("version", help="print version")

    serve = sub.add_parser("serve", help="run the backend server")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        from .doctor import main as doctor_main

        return doctor_main()

    if args.command == "version":
        print(f"aicut {__version__}")
        return 0

    if args.command == "serve":
        from .config import get_settings

        settings = get_settings()
        host = args.host or settings.host
        port = args.port or settings.port
        import uvicorn

        uvicorn.run(
            "aicut.app:app",
            host=host,
            port=port,
            reload=args.reload,
        )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
