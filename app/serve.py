"""Run the original Atlas HTTP application in a local or container deployment."""
import argparse
import importlib.util
import os
from http.server import ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Atlas PVZ demo server")
    parser.add_argument("--host", default=os.getenv("PVZ_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=os.getenv("PVZ_PORT", "8080"))
    args = parser.parse_args()
    with Path(__file__).with_name("server.pyc").open("rb") as module:
        if module.read(4) != importlib.util.MAGIC_NUMBER:
            parser.exit(2, "Atlas backend requires CPython 3.15.1. Use Docker Compose or the Windows release.\n")
    import server
    server.bootstrap()
    with ThreadingHTTPServer((args.host, args.port), server.Handler) as http:
        print(f"Atlas PVZ http://{args.host}:{http.server_port}", flush=True)
        try:
            http.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
