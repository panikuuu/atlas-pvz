"""End-to-end checks on a freshly provisioned, private Atlas instance."""
import argparse
from collections import Counter
from contextlib import contextmanager
import json
import os
from pathlib import Path
from queue import Queue, Empty
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def request(base, path, body=None, role="dispatcher"):
    headers = {"X-Role": role}
    payload = None
    if body is not None:
        headers.update({"Content-Type": "application/json", "Idempotency-Key": str(uuid4())})
        payload = json.dumps(body).encode()
    with urlopen(Request(base + path, payload, headers), timeout=15) as response:
        return json.load(response)


@contextmanager
def isolated_server(app, exe=None):
    with TemporaryDirectory(prefix="atlas-ci-") as temp:
        env = dict(os.environ, PVZ_DATA=temp, PVZ_DEMO="1", PVZ_QUIET="1", PYTHONIOENCODING="utf-8")
        command = [sys.executable, str(app / "serve.py"), "--port", "0", "--host", "127.0.0.1"]
        if exe:
            copied = shutil.copy2(exe, Path(temp) / "Atlas-PVZ.exe")
            command = [str(copied), "--no-browser"]
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        found = Queue()
        def read_address():
            for line in process.stdout:
                match = re.search(rb"http://127\.0\.0\.1:\d+", line)
                if match:
                    found.put(match.group().decode())
                    return
            found.put(None)
        threading.Thread(target=read_address, daemon=True).start()
        try:
            try:
                url = found.get(timeout=40)
            except Empty:
                raise RuntimeError("The local server did not report a listening address") from None
            if not url:
                raise RuntimeError("The local server exited before startup")
            yield url
        finally:
            if process.poll() is None:
                if exe and os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, check=False)
                else:
                    process.terminate()
            process.wait(timeout=15)
            process.stdout.close()


def verify(base):
    request(base, "/health/ready")
    request(base, "/health/live")
    with urlopen(base + "/", timeout=10) as page:
        assert 'Атлас доставки' in page.read().decode("utf-8")
    for role in ("pvz", "seller"):
        request(base, "/api/stock", role=role)
        try:
            request(base, "/api/demo/run", {}, role=role)
        except HTTPError as error:
            assert error.code == 403, (role, error.code)
        else:
            raise AssertionError(f"{role} was able to run a dispatcher action")
    expected = {
        "case1": ("SHARED_TRIP", {"ISSUED": 10}),
        "case2": ("HUB", {"ISSUED": 1}),
        "case3": ("SHARED_TRIP", {"ISSUED": 9, "RESTOCKED": 1}),
        "case4": ("SHARED_TRIP", {"ISSUED": 10}),
        "case5": (None, {}),
        "rural": ("SHARED_TRIP", {"ISSUED": 2}),
    }
    for case, (route, statuses) in expected.items():
        request(base, "/api/demo/reset", {"scenario": case})
        assert request(base, "/api/demo/run", {})["finished"]
        state = request(base, "/api/state")
        assert (state["quote"] or {}).get("selected") == route, case
        assert Counter(x["status"] for x in state["orders"]) == statuses, case
        assert state["ledger_errors"] == state["stock_errors"] == 0, case
        if case == "case4":
            replay = state["replay_check"]
            assert replay["ledger"] == replay["movements"] == replay["incidents"] == 0
            assert replay["changed_body_status"] == 409
        if case == "case5":
            assert state["alerts"][0]["reason"] == "STORAGE_LIMIT"
            assert state["lots"][0]["at_hub"] == 1 and state["lots"][0]["occupied_l"] == 0
        print(f"PASS {case}: {route}, {statuses}", flush=True)
    request(base, "/api/profile", {"profile": "pilot"})
    for demand, orders, direct, rubles in [
        ("low", 568, 260, -14154), ("neutral", 792, 500, 1531), ("high", 1016, 672, 14494)
    ]:
        portfolio = request(base, f"/api/portfolio?demand={demand}&consent=0")
        assert portfolio["profile"] == "pilot" and portfolio["scenario"] == demand, portfolio
        assert (portfolio["orders"], portfolio["direct"]) == (orders, direct), portfolio
        assert round(portfolio["rwb_delta"] / 100) == rubles, portfolio
        print(f"PASS portfolio/{demand}: {orders} orders, {direct} direct, {rubles} RUB", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[1] / "app")
    parser.add_argument("--exe", type=Path, help="Windows release executable to test in a temporary directory")
    args = parser.parse_args()
    with isolated_server(args.app.resolve(), args.exe) as base:
        verify(base)
