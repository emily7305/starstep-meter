"""Run the api: python -m backend.api [--host 127.0.0.1] [--port 8000]"""

from __future__ import annotations

import argparse
import ipaddress
import sys

import uvicorn

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def is_loopback(host: str) -> bool:
    # uvicorn accepts [::1] style too, strip the brackets before parsing
    host = host.strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        # a hostname we can't vouch for, treat it as reachable
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.api", description="run the starstep-meter api")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"interface to listen on (default {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    if not is_loopback(args.host):
        print(f"warning: listening on {args.host}, anyone who can reach this machine can upload files and read results", file=sys.stderr)

    # no reload, every restart re-imports librosa and that's slow enough to be annoying
    uvicorn.run("backend.api.app:app", host=args.host, port=args.port, reload=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
