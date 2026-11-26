"""End-to-end checks on a freshly provisioned, private Atlas instance."""
import argparse
from collections import Counter
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
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


def request(base, path, body=None, role="dispatcher", key=None):
    headers = {"X-Role": role}
    payload = None
    if body is not None:
        headers.update({"Content-Type": "application/json", "Idempotency-Key": key or str(uuid4())})
        payload = json.dumps(body).encode()
    with urlopen(Request(base + path, payload, headers), timeout=15) as response:
        return json.load(response)


@contextmanager
def isolated_server(app, exe=None, *, data_dir=None, demo=True):
    with (TemporaryDirectory(prefix="atlas-ci-") if data_dir is None else nullcontext(data_dir)) as temp:
        env = dict(os.environ, PVZ_DATA=str(temp), PVZ_DEMO=str(int(demo)), PVZ_QUIET="1", PYTHONIOENCODING="utf-8")
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


def verify_nine_points(base):
    request(base, "/api/demo/reset", {"scenario": "sandbox"})
    ring = "AEFGJKCDB"
    ids = set(ring)
    state = request(base, "/api/state")
    assert {p["id"] for p in state["points"]} == ids
    assert all(p["free_l"] == p["capacity_l"] and p["free_l"] > 0 for p in state["points"])
    assert {p["id"] for p in request(base, "/api/map")["points"]} == ids
    assert {p["id"] for p in request(base, "/api/map?view=plan")["points"]} == ids
    assert state["totals"]["pvz_profit"] == dict.fromkeys(ids, 0)
    demand = request(base, "/api/fleet", {"action": "plan", "scenario": "network"})["plan"]
    assert {p["point"] for p in demand["economics"]["by_pvz"] if p["work_minutes"]} == ids

    promised = (datetime.fromisoformat(state["now"]) + timedelta(days=3)).isoformat()
    for source, destination in zip(ring, ring[1:] + ring[:1]):
        lot_id = "LOT-" + source
        body = {"lot_id": lot_id, "sku_id": "S", "pvz_id": source, "quantity": 1}
        lot = request(base, "/api/receipts", body, role="pvz")
        assert lot["pvz_id"] == source and lot["available"] == 1
        stock = request(base, "/api/stock?pvz_id=" + source)
        assert stock[0]["pvz_id"] == source and stock[0]["occupied_l"] == 2
        order = request(base, "/api/orders", {"lot_id": lot_id, "quantity": 1, "pvz_id": destination,
                                               "promised_at": promised, "expected_version": lot["version"]})
        oid = order["id"]

        def scan(event, point):
            item = request(base, "/api/orders/" + oid)
            return request(base, "/api/events", {"order_id": oid, "event_type": event, "pvz_id": point,
                                                  "quantity": 1, "expected_version": item["version"]}, role="pvz")

        scan("ASSEMBLED", source)
        current = request(base, "/api/direction", {"source": source, "destination": destination})
        if source == "A":
            request(base, "/api/settings", {"settings": {"shared_slots": 1, "shared_liters": 2,
                    "shared_grams": 600, "shared_ready_hours": 3, "detour_km": 0, "detour_minutes": 0}})
        quote = request(base, "/api/routing/quotes", {"order_ids": [oid], "window_id": current["window_id"],
                                                     "scenario_version": state["fixture_version"]})
        assert quote["selected"] != "MANUAL_EXCEPTION", (source, destination, quote["reason"])
        if source == "A":
            assert quote["selected"] == "SHARED_TRIP", quote["selected"]
        request(base, "/api/dispatches", {"quote_id": quote["quote_id"], "selected": quote["selected"],
                                         "expected_version": quote["version"]})
        scan("HANDED_OVER", source)
        scan("ARRIVED", destination)
        point = next(p for p in request(base, "/api/state")["points"] if p["id"] == destination)
        assert point["occupied_l"] == 2
        scan("ISSUED", destination)
        order = request(base, "/api/orders/" + oid)
        assert (order["source"], order["destination"], order["status"]) == (source, destination, "ISSUED")
        rural = any(point in "CDGJK" for point in (source, destination))
        assert order["financials"]["central_contribution"] == (7800 if rural else 12400)

    state = request(base, "/api/state")
    assert state["ledger_errors"] == state["stock_errors"] == 0
    assert {p["id"]: p["occupied_l"] for p in state["points"]} == dict.fromkeys(ids, 0)
    totals = state["totals"]
    assert set(totals["pvz_revenue"]) == set(totals["pvz_cost"]) == set(totals["pvz_profit"]) == ids
    for point in ids:
        ledger = request(base, "/api/ledger?pvz_id=" + point)
        for service, party in (("RECEIVE", "to_party"), ("ASSEMBLY", "to_party"), ("PICKUP", "to_party")):
            assert any(entry["service"] == service and entry[party] == point for entry in ledger)
        income = sum(entry["amount"] for entry in ledger if entry["to_party"] == point)
        cost = sum(entry["amount"] for entry in ledger if entry["from_party"] == point)
        assert (totals["pvz_revenue"][point], totals["pvz_cost"][point], totals["pvz_profit"][point]) == (
            income, cost, income - cost)
    for bad_point in ("E", "HUB"):
        try:
            request(base, "/api/direction", {"source": "E", "destination": bad_point})
        except HTTPError as error:
            assert error.code == 422, (bad_point, error.read())
        else:
            raise AssertionError(f"Unexpected valid direction E → {bad_point}")
    print("PASS all nine PVZ: warehouse, dispatch, received orders, ledger totals and planning", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[1] / "app")
    parser.add_argument("--exe", type=Path, help="Windows release executable to test in a temporary directory")
    args = parser.parse_args()
    with isolated_server(args.app.resolve(), args.exe) as base:
        verify(base)
        verify_nine_points(base)
