"""HTTP and SQLite regressions for rare-stock placement and warehouse custody."""

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

from test_cases import isolated_server, request


APP = Path(__file__).resolve().parents[1] / "app"
STOCK = "/api/stock-placement"
SKU = "SMARTPHONE"


def accept(base, lot_id, point):
    request(base, "/api/receipts", {"lot_id": lot_id, "sku_id": SKU, "pvz_id": point,
                                  "quantity": 1, "sale_price": 7_000_000, "cost_price": 5_000_000}, role="pvz")


def placement(base, lot_id):
    return next(row for row in request(base, STOCK)["rows"] if row["lot_id"] == lot_id)


def option(row, point):
    return next(item for item in row["options"] if item["point"] == point)


def confirm_payload(row):
    return {"action": "confirm", **{key: row[key] for key in ("lot_id", "source", "fingerprint")}}


def order(base, lot_id, point, source=None):
    state = request(base, "/api/state")
    due = (datetime.fromisoformat(state["now"]) + timedelta(days=4)).isoformat()
    body = {"lot_id": lot_id, "pvz_id": point, "quantity": 1, "promised_at": due, "delivery_price": 1250}
    if source:
        body["stock_source_pvz_id"] = source
    return request(base, "/api/orders", body)


def scan(base, order_id, event, point):
    item = request(base, "/api/orders/" + order_id)
    return request(base, "/api/events", {"order_id": order_id, "event_type": event, "pvz_id": point,
                                        "quantity": 1, "expected_version": item["version"]}, role="pvz")


class PlacementTests(unittest.TestCase):
    def status(self, code, fn, *args, **kwargs):
        with self.assertRaises(HTTPError) as raised:
            fn(*args, **kwargs)
        with raised.exception as response:
            self.assertEqual(response.code, code, response.read())

    def test_rural_order_is_fulfilled_without_local_replenishment(self):
        with isolated_server(APP, demo=False) as base:
            direction = request(base, "/api/direction", {"source": "C", "destination": "D"})
            accept(base, "PHONE-C", "C")
            recommendation = request(base, STOCK)
            self.assertEqual(request(base, STOCK), recommendation)
            row = placement(base, "PHONE-C")
            self.assertIsNone(option(row, "D")["demand_index"])
            self.assertFalse(option(row, "D")["eligible"])
            sale = order(base, "PHONE-C", "D")
            oid = sale["id"]
            self.status(409, request, base, STOCK, confirm_payload(row))
            self.assertEqual(request(base, STOCK)["rows"], [])
            scan(base, oid, "ASSEMBLED", "C")
            state = request(base, "/api/state")
            quote = request(base, "/api/routing/quotes", {"order_ids": [oid], "window_id": direction["window_id"],
                                                          "scenario_version": state["fixture_version"]})
            self.assertNotEqual(quote["selected"], "MANUAL_EXCEPTION")
            request(base, "/api/dispatches", {"quote_id": quote["quote_id"], "selected": quote["selected"],
                                              "expected_version": quote["version"]})
            for event, point, status in (("HANDED_OVER", "C", "IN_TRANSIT"),
                                          ("ARRIVED", "D", "READY_FOR_PICKUP"),
                                          ("ISSUED", "D", "ISSUED")):
                self.assertEqual(scan(base, oid, event, point)["status"], status)
                self.assertEqual(request(base, STOCK)["rows"], [])
            record = request(base, "/api/orders/" + oid)
            self.assertEqual(record["promised_at"], sale["promised_at"])
            self.assertEqual(record["buyer_delivery_price"], 1250)
            self.assertEqual(record["sale_price"], 7_000_000)
            request(base, "/api/demand", {"action": "recalculate"})
            rural = next(row for row in request(base, "/api/demand")["rows"]
                         if row["sku"] == SKU and row["zone"] == "D")
            self.assertEqual((rural["unique_orders"], rural["demand_index"], rural["forecast_units"],
                              rural["confidence"], rural["recommendation"]["units"]), (1, 0, .8, "low", 0))

    def test_surge_changes_variant_and_confirmed_stock_survives_restart(self):
        with TemporaryDirectory(prefix="atlas-placement-") as storage:
            with isolated_server(APP, data_dir=storage) as base:
                request(base, "/api/demo/reset", {"scenario": "sandbox"})
                accept(base, "PHONE-A", "A")
                baseline = placement(base, "PHONE-A")
                unchanged = request(base, "/api/state")
                self.assertEqual(baseline["recommendation"]["action"], "keep")
                self.assertGreater(option(baseline, "A")["net"], option(baseline, "HUB")["net"])
                request(base, "/api/demand", {"action": "surge"})
                surge = placement(base, "PHONE-A")
                current = request(base, "/api/state")
                for key in ("points", "settings"):
                    self.assertEqual(current[key], unchanged[key])
                self.assertEqual((option(baseline, "B")["demand_index"], option(baseline, "B")["forecast_units"]),
                                 (10, 3.6))
                self.assertEqual((option(surge, "B")["demand_index"], option(surge, "B")["forecast_units"]),
                                 (77, 21.6))
                self.assertEqual(surge["recommendation"]["point"], "B")
                self.assertGreater(option(surge, "B")["net"], max(option(surge, "HUB")["net"], option(surge, "A")["net"]))
                self.status(409, request, base, STOCK, confirm_payload(baseline))
                self.status(403, request, base, STOCK, role="seller")
                payload = confirm_payload(surge)
                self.status(403, request, base, STOCK, payload, role="pvz")
                confirmed = request(base, STOCK, payload, key="move-a-to-b")
                self.assertEqual(confirmed, request(base, STOCK, payload, key="move-a-to-b"))
                self.status(409, request, base, STOCK, payload)
                transfer = confirmed["transfer"]
                transfer_id = transfer["id"]
                self.assertEqual(transfer["status"], "RESERVED")
                self.assertEqual(request(base, STOCK)["rows"], [])
                self.status(409, order, base, "PHONE-A", "B")
                self.status(409, request, base, STOCK, {"action": "receive", "transfer_id": transfer_id})
                request(base, STOCK, {"action": "send", "transfer_id": transfer_id})
                self.assertEqual(request(base, STOCK)["rows"], [])

            with isolated_server(APP, data_dir=storage) as base:
                self.assertEqual(request(base, STOCK)["transfers"][0]["status"], "IN_TRANSIT")
                received = request(base, STOCK, {"action": "receive", "transfer_id": transfer_id})["transfer"]
                self.assertEqual(received["status"], "RECEIVED")
                self.assertEqual([entry["action"] for entry in received["journal"]],
                                 ["PLACEMENT_RESERVED", "PLACEMENT_SENT", "PLACEMENT_RECEIVED"])
                self.assertEqual(request(base, "/api/stock?pvz_id=B")[0]["positions"], {"B:AVAILABLE": 1})
                sale = order(base, "PHONE-A", "B", "B")
                oid = sale["id"]
                self.assertEqual(sale["unit_id"], transfer["unit_id"])
                self.assertEqual(scan(base, oid, "ASSEMBLED", "B")["status"], "READY_FOR_PICKUP")
                self.assertEqual(request(base, STOCK)["rows"], [])
                self.assertEqual(scan(base, oid, "ISSUED", "B")["status"], "ISSUED")
                state = request(base, "/api/state")
                self.assertEqual((state["stock_errors"], state["ledger_errors"]), (0, 0))
                self.assertEqual(len([move for move in state["movements"] if move["event_id"] in
                                      {entry["event_id"] for entry in received["journal"]}]), 3)

    def test_cheaper_hub_beats_relocation_and_reservation_can_be_cancelled(self):
        with isolated_server(APP) as base:
            request(base, "/api/demo/reset", {"scenario": "sandbox"})
            accept(base, "PHONE-A", "A")
            request(base, "/api/demand", {"action": "surge"})
            self.status(422, request, base, STOCK, {"action": "configure", "settings": {"annual_capital": 2}})
            request(base, STOCK, {"action": "configure", "settings": {"km_cost": 0, "hub_transfer_fixed": 0,
                                                                     "hub_sale_delivery": 0}})
            row = placement(base, "PHONE-A")
            self.assertEqual(row["recommendation"]["action"], "hub")
            self.assertGreater(option(row, "HUB")["net"], option(row, "B")["net"])
            transfer = request(base, STOCK, confirm_payload(row))["transfer"]
            cancelled = request(base, STOCK, {"action": "cancel", "transfer_id": transfer["id"]})["transfer"]
            self.assertEqual(cancelled["status"], "CANCELLED")
            self.assertEqual(placement(base, "PHONE-A")["available"], 1)
            transfer = request(base, STOCK, confirm_payload(placement(base, "PHONE-A")))["transfer"]
            for action in ("send", "receive"):
                transfer = request(base, STOCK, {"action": action, "transfer_id": transfer["id"]})["transfer"]
            self.assertEqual((transfer["destination"], transfer["status"]), ("HUB", "RECEIVED"))
            self.assertEqual(placement(base, "PHONE-A")["source"], "HUB")


if __name__ == "__main__":
    unittest.main()
