"""Exercise settlement resolution and routing through the Atlas HTTP API."""

from contextlib import closing
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from urllib.error import HTTPError

from test_cases import isolated_server, request


APP = Path(__file__).resolve().parents[1] / "app"


def create_order(base, order_id, source, destination, *, due=timedelta(days=3), **fields):
    current = request(base, "/api/state")
    promised = datetime.fromisoformat(current["now"]) + due
    lot = request(base, "/api/receipts", {
        "lot_id": f"LOT-{order_id}", "sku_id": "S", "pvz_id": source, "quantity": 1,
    }, role="pvz")
    request(base, "/api/orders", {
        "order_id": order_id, "lot_id": lot["id"], "pvz_id": destination,
        "quantity": 1, "promised_at": promised.isoformat(), **fields,
    })
    scan(base, order_id, "ASSEMBLED", source)
    return request(base, f"/api/orders/{order_id}")


def scan(base, order_id, event_type, point):
    order = request(base, f"/api/orders/{order_id}")
    return request(base, "/api/events", {
        "order_id": order_id, "event_type": event_type, "pvz_id": point, "quantity": 1,
        "expected_version": order["version"],
    }, role="pvz")


def quote(base, *order_ids):
    state = request(base, "/api/state")
    return request(base, "/api/routing/quotes", {
        "order_ids": order_ids, "window_id": state["window_id"],
        "scenario_version": state["fixture_version"],
    })


def open_shared_window(base, *, ready_hours=12):
    request(base, "/api/settings", {"settings": {
        "shared_slots": 2, "shared_liters": 4, "shared_grams": 1200,
        "shared_ready_hours": ready_hours, "detour_km": 0, "detour_minutes": 0,
    }})


def direct_candidate(proposal):
    return next(item for item in proposal["candidates"] if item["mode"] == "SHARED_TRIP")


class GeographyTests(unittest.TestCase):
    def setUp(self):
        self.base = None

    def start_sandbox(self, app=APP):
        server = isolated_server(app)
        self.base = server.__enter__()
        self.addCleanup(server.__exit__, None, None, None)
        request(self.base, "/api/demo/reset", {"scenario": "sandbox"})
        return self.base

    def assert_http_error(self, status, code, action):
        with self.assertRaises(HTTPError) as raised:
            action()
        with closing(raised.exception) as response:
            self.assertEqual(response.code, status)
            self.assertEqual(json.load(response)["error"], code)

    def test_city_id_is_shared_by_distinct_points_and_capacity_still_applies(self):
        base = self.start_sandbox()
        order = create_order(base, "LOCAL", "A", "B", seller_ship_from_pvz_id="E")
        geo = order["geography"]
        self.assertEqual((geo["relation"], geo["route_scope"]), ("same_locality", "local"))
        seller, buyer = geo["seller_ship_from"], geo["buyer_pickup"]
        self.assertEqual((seller["point_id"], buyer["point_id"]), ("E", "B"))
        self.assertEqual(seller["locality"]["id"], buyer["locality"]["id"])
        self.assertEqual(buyer["locality"]["type"], "city")
        self.assertIsNone(geo["direct_block"])
        self.assertTrue(geo["reason"])
        self.assertEqual(request(base, "/api/state")["orders"][0]["geography"], geo)

        open_shared_window(base)
        self.assertEqual(quote(base, order["id"])["selected"], "SHARED_TRIP")
        open_shared_window(base, ready_hours=96)
        late = quote(base, order["id"])
        self.assertEqual(late["selected"], "HUB")
        self.assertEqual(direct_candidate(late)["reason"], "DEADLINE_MISSED")
        open_shared_window(base)
        request(base, "/api/settings", {"settings": {"shared_slots": 0, "dedicated_slots": 0}})
        closed = quote(base, order["id"])
        self.assertEqual(closed["selected"], "HUB")
        self.assertFalse(direct_candidate(closed)["eligible"])
        self.assertEqual(direct_candidate(closed)["reason"], "NO_CAPACITY")

    def test_identically_named_localities_across_regions_have_distinct_ids(self):
        base = self.start_sandbox()
        geo = create_order(base, "HOMONYMS", "D", "K")["geography"]
        north = geo["seller_ship_from"]["locality"]
        south = geo["buyer_pickup"]["locality"]
        self.assertEqual(north["name"], south["name"])
        self.assertNotEqual(north["id"], south["id"])
        self.assertNotEqual(north["region_id"], south["region_id"])
        self.assertEqual((geo["relation"], geo["route_scope"]), ("different_localities", "rural"))
        self.assertGreater(geo["road_km"], 0)

    def test_city_and_village_can_use_a_profitable_rural_shared_trip(self):
        base = self.start_sandbox()
        request(base, "/api/direction", {"source": "A", "destination": "D"})
        order = create_order(base, "RURAL", "A", "D")
        geo = order["geography"]
        self.assertEqual((geo["relation"], geo["route_scope"]), ("different_localities", "rural"))
        self.assertEqual(geo["seller_ship_from"]["locality"]["type"], "city")
        self.assertEqual(geo["buyer_pickup"]["locality"]["type"], "village")
        self.assertGreater(geo["road_km"], 0)

        open_shared_window(base)
        rural = quote(base, order["id"])
        self.assertEqual(rural["selected"], "SHARED_TRIP")
        self.assertGreater(rural["savings"], 0)

    def test_route_and_handoff_start_at_stock_even_when_seller_matches_buyer(self):
        base = self.start_sandbox()
        order = create_order(base, "PREPOSITIONED", "C", "B", seller_ship_from_pvz_id="A")
        geo = order["geography"]
        self.assertEqual(order["seller_ship_from_pvz_id"], "A")
        self.assertEqual(order["source"], "C")
        self.assertEqual(geo["stock_start"]["point_id"], "C")
        self.assertEqual((geo["relation"], geo["route_scope"]), ("same_locality", "rural"))
        self.assert_http_error(422, "DIRECTION_MISMATCH", lambda: quote(base, order["id"]))

        request(base, "/api/direction", {"source": "C", "destination": "B"})
        open_shared_window(base)
        proposal = quote(base, order["id"])
        self.assertEqual(proposal["selected"], "SHARED_TRIP")
        request(base, "/api/dispatches", {
            "quote_id": proposal["quote_id"], "selected": proposal["selected"],
            "expected_version": proposal["version"],
        })
        self.assert_http_error(409, "WRONG_PVZ", lambda: scan(base, order["id"], "HANDED_OVER", "A"))
        self.assertEqual(scan(base, order["id"], "HANDED_OVER", "C")["status"], "IN_TRANSIT")

    def test_unknown_seller_geography_can_be_routed_through_hub(self):
        base = self.start_sandbox()
        known = create_order(base, "KNOWN", "A", "B")
        unknown = create_order(base, "UNKNOWN", "A", "B", seller_ship_from_pvz_id=None)
        geo = unknown["geography"]
        self.assertIsNone(unknown["seller_ship_from_pvz_id"])
        self.assertEqual(geo["relation"], "unknown")
        self.assertEqual(geo["seller_ship_from"], {"point_id": None, "locality": None})
        self.assertEqual(geo["direct_block"], "UNKNOWN_GEOGRAPHY")
        self.assertTrue(geo["reason"])

        open_shared_window(base)
        self.assertEqual(quote(base, known["id"])["selected"], "SHARED_TRIP")
        proposal = quote(base, unknown["id"])
        self.assertEqual(proposal["selected"], "HUB")
        self.assertEqual(direct_candidate(proposal)["reason"], "UNKNOWN_GEOGRAPHY")
        mixed = quote(base, known["id"], unknown["id"])
        self.assertEqual(mixed["allocations"]["SHARED_TRIP"], [known["id"]])
        self.assertEqual(mixed["allocations"]["HUB"], [unknown["id"]])

        fleet = request(base, "/api/fleet", {
            "action": "plan", "scenario": "live", "allow_transfer": False,
            "trucks": [{"id": "check", "start": "A", "end": "B", "start_min": 550,
                        "end_min": 700, "liters": 20, "kg": 10, "planned": True}],
            "prices": {"hub_city": 9000, "coordination_day": 0},
        })["plan"]
        self.assertEqual({o["id"]: o["channel"] for o in fleet["financials"]["orders"]},
                         {known["id"]: "fleet", unknown["id"]: "hub"})
        self.assertEqual(fleet["economics"]["hub_remaining"][0]["direct_block"], "UNKNOWN_GEOGRAPHY")

    def test_reservation_and_pickup_from_the_same_point_need_no_vehicle(self):
        base = self.start_sandbox()
        order = create_order(base, "ON-SHELF", "D", "D", stock_source_pvz_id="D",
                             seller_ship_from_pvz_id="A", delivery_price=1234)
        self.assertEqual(order["status"], "READY_FOR_PICKUP")
        self.assertEqual(order["mode"], "LOCAL_PICKUP")
        self.assertEqual(order["delivery_price"], 1234)
        self.assertEqual(order["promised_at"], order["original_promised_at"])
        self.assertEqual(order["geography"]["relation"], "different_localities")
        self.assertEqual(order["geography"]["route_scope"], "local")
        self.assertEqual(order["geography"]["road_km"], 0)
        self.assertEqual(order["geography"]["stock_start"]["point_id"], "D")
        self.assertIsNone(order["manifest"])
        self.assertEqual([m["to"] for m in order["movements"]], ["D:RESERVED", "D:ASSEMBLED", "D:READY"])
        self.assertEqual(scan(base, order["id"], "ISSUED", "D")["status"], "ISSUED")
        state = request(base, "/api/state")
        self.assertEqual((state["stock_errors"], state["ledger_errors"]), (0, 0))

    def test_migration_preserves_legacy_orders_and_infers_their_shipment_point(self):
        with TemporaryDirectory() as data:
            env = dict(os.environ, PVZ_DATA=data, PVZ_DEMO="1", PVZ_QUIET="1")
            subprocess.run(
                [sys.executable, "-B", "-c",
                 "import server; server.bootstrap(); server.execute('/api/demo/run', 'dispatcher', {}, 'run')"],
                cwd=APP, env=env, check=True, timeout=20,
            )
            with closing(sqlite3.connect(Path(data) / "catalog.sqlite")) as catalog:
                workspace = Path(data) / catalog.execute("SELECT name FROM active").fetchone()[0]
            with closing(sqlite3.connect(workspace)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                columns = ", ".join(row[1] for row in db.execute("PRAGMA table_info(op_orders)"))
                old_rows = db.execute(f"SELECT {columns} FROM op_orders ORDER BY id").fetchall()
                self.assertEqual(len(old_rows), 10)

            with isolated_server(APP, data_dir=data, demo=False) as base:
                order = request(base, "/api/orders/O01")
                self.assertEqual((order["seller_ship_from_pvz_id"], order["source"], order["destination"]),
                                 ("A", "A", "B"))
                self.assertEqual(order["status"], "ISSUED")
                self.assertEqual(order["geography"]["relation"], "same_locality")
            with closing(sqlite3.connect(workspace)) as db:
                self.assertGreaterEqual(db.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(db.execute(f"SELECT {columns} FROM op_orders ORDER BY id").fetchall(), old_rows)
            with isolated_server(APP, data_dir=data, demo=False) as base:
                self.assertEqual(request(base, "/api/orders/O01")["geography"], order["geography"])


if __name__ == "__main__":
    unittest.main()
