"""Verify one demo day through the same API and SQLite workspace used by the UI."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError

from test_cases import isolated_server, request


def expect_status(call, status):
    try:
        call()
    except HTTPError as error:
        assert error.code == status, (error.code, error.read())
    else:
        raise AssertionError(f"Expected HTTP {status}")


def verify(base):
    request(base, "/api/demo/reset", {"scenario": "sandbox"})
    start = {"action": "unified-start"}
    assert request(base, "/api/fleet")["unified"] is None
    expect_status(lambda: request(base, "/api/fleet", start, role="pvz"), 403)
    snapshot = request(base, "/api/fleet", start)["unified"]
    assert snapshot["stage"] == 0

    for stage in range(1, 7):
        action = {"action": "unified-next", "version": snapshot["version"]}
        key = f"verify-unified-{stage}"
        result = request(base, "/api/fleet", action, key=key)
        snapshot = result["unified"]
        assert snapshot["stage"] == stage
        assert request(base, "/api/fleet", action, key=key) == result
        expect_status(lambda: request(base, "/api/fleet", action), 409)
        state = request(base, "/api/state")
        assert snapshot["summary"]["ledger_entries"] == len(state["ledger"])
        assert state["stock_errors"] == state["ledger_errors"] == 0
        if stage == 3:
            assert result["unified"]["summary"]["plan"] == {
                "all_hub": 376500, "total": 180034, "savings": 196466,
                "orders": 35, "fleet_orders": 34, "hub_orders": 1, "relayed_orders": 10,
            }
        if stage == 4:
            assert any(row["kind"] == "relay" and row["owner"] == "C" for row in result["day"]["custody"].values())
            assert any(movement["to"] == "RELAY:C" for movement in state["movements"])

    assert snapshot["finished"] and snapshot["next_label"] is None
    assert snapshot["summary"] == {
        "orders": 36, "assembled": 0, "ready": 0, "issued": 35, "returned": 1, "hub_orders": 1, "incidents": 1,
        "ledger_entries": 575, "plan": snapshot["summary"]["plan"],
        "actual": {"rwb_cost": 262798, "rwb_contribution": 1901567, "seller_profit": 1103635, "pvz_profit": 77218},
    }
    assert {point["id"] for point in state["points"]} == set("ABCDEFGJK")
    hub = request(base, "/api/orders/UD-HUB-01")
    assert hub["mode"] == "HUB" and hub["status"] == "ISSUED"
    assert hub["geography"]["relation"] == "different_localities"
    assert [entry["amount"] for entry in hub["ledger"] if entry["service"] == "RECOVERY"] == [7500]
    assert not any(row["status"] == "OPEN" for row in state["incidents"])
    relay = request(base, "/api/orders/UD-RELAY-01")
    assert any(movement["to"] == "RELAY:C" for movement in relay["movements"])
    assert sum(entry["service"] == "SELLER_LOGISTICS" for entry in relay["ledger"]) == 1
    customer = request(base, "/api/orders/UD-PHONE-01")
    assert customer["geography"]["relation"] == "different_localities"
    assert customer["geography"]["stock_start"]["point_id"] == customer["destination"] == "D"
    assert customer["mode"] == "LOCAL_PICKUP"
    assert request(base, "/api/orders/UD-CITY-01")["geography"]["relation"] == "same_locality"
    assert state["totals"]["on_time"] == state["totals"]["ready_count"] == 36
    aged = next(lot for lot in state["lots"] if lot["id"] == "UD-AGED")
    assert aged["at_hub"] == 1 and aged["occupied_l"] == 0
    assert request(base, "/api/orders/UD-CITY-01")["status"] == "RESTOCKED"
    return snapshot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, default=Path(__file__).resolve().parents[1] / "app")
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="atlas-unified-") as temp:
        with isolated_server(args.app.resolve(), args.exe, data_dir=temp) as base:
            completed = verify(base)
        with isolated_server(args.app.resolve(), args.exe, data_dir=temp) as base:
            assert request(base, "/api/fleet")["unified"] == completed
            request(base, "/api/demo/reset", {"scenario": "sandbox"})
            assert request(base, "/api/fleet")["unified"] is None
    print("PASS unified day: orders, hub recovery, relay, geography, oldest stock, ledger, replay and restart", flush=True)
