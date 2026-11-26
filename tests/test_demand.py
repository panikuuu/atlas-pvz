"""Check demand through the standard HTTP server, including SQLite migration and replay."""

from contextlib import closing
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
PATH = "/api/demand"


def row(report, zone="", region="Северная область", sku="S"):
    return next(item for item in report["rows"]
                if (item["sku"], item["region"], item["zone"]) == (sku, region, zone))


class DemandTests(unittest.TestCase):
    def test_history_changes_recommendation_and_survives_restart(self):
        with TemporaryDirectory() as data:
            with isolated_server(APP, data_dir=data) as base:
                initial = request(base, PATH)
                self.assertEqual(row(initial)["demand_index"], 87)
                self.assertEqual(row(initial, region="Южная область")["demand_index"], 19)
                self.assertNotEqual(row(initial)["region_id"],
                                    row(initial, region="Южная область")["region_id"])
                rural = row(initial, "D")
                self.assertEqual((rural["unique_orders"], rural["demand_index"], rural["confidence"],
                                  rural["recommendation"]["units"]), (1, 0, "low", 0))
                phone_rural = row(initial, "D", sku="SMARTPHONE")
                self.assertEqual((phone_rural["locality_type"], phone_rural["unique_orders"],
                                  phone_rural["demand_index"], phone_rural["forecast_units"],
                                  phone_rural["confidence"], phone_rural["recommendation"]["units"]),
                                 ("village", 1, 0, 0.8, "low", 0))
                missing = row(initial, "K", "Южная область")
                self.assertEqual((missing["demand_index"], missing["forecast_units"], missing["confidence"]),
                                 (None, None, "low"))

                original_state = request(base, "/api/state")
                original = row(initial, "B")
                self.assertEqual((original["unique_orders"], original["demand_index"], original["forecast_units"],
                                  original["recommendation"]["units"]), (6, 10, 3.6, 0))
                first = request(base, PATH, {"action": "surge"}, key="surge")
                self.assertEqual(first, request(base, PATH, {"action": "surge"}, key="surge"))
                # Re-applying with another request key still updates the same canonical order IDs.
                request(base, PATH, {"action": "surge"})
                surge = request(base, PATH)
                current = row(surge, "B")
                self.assertEqual((current["unique_orders"], current["demand_index"], current["forecast_units"],
                                  current["recommendation"]["units"]), (34, 77, 21.6, 10))
                phone_city = row(surge, "B", sku="SMARTPHONE")
                self.assertEqual((phone_city["unique_orders"], phone_city["demand_index"],
                                  phone_city["forecast_units"], phone_city["confidence"]), (34, 77, 21.6, "high"))
                self.assertNotEqual(phone_rural["locality_id"], phone_city["locality_id"])
                self.assertEqual(row(surge, "D", sku="SMARTPHONE")["demand_index"], 0)
                for field in ("on_hand", "free_liters", "shelf_units", "transport_units"):
                    self.assertEqual(original["recommendation"][field], current["recommendation"][field])
                current_state = request(base, "/api/state")
                for field in ("settings", "points", "lots", "orders"):
                    self.assertEqual(current_state[field], original_state[field])

            with isolated_server(APP, data_dir=data) as base:
                self.assertEqual(request(base, PATH), surge)
                request(base, PATH, {"action": "baseline"})
                self.assertEqual(row(request(base, PATH), "B")["unique_orders"], 6)
                # Case 4 issues ten orders and replays the first issuance and arrival scans.
                request(base, "/api/demo/reset", {"scenario": "case4"})
                request(base, "/api/demo/run", {})
                request(base, PATH, {"action": "recalculate"})
                self.assertEqual(row(request(base, PATH), "B")["unique_orders"], 16)
                self.assertEqual(request(base, "/api/state")["replay_check"]["replayed"], 2)

    def test_existing_database_is_migrated_without_changing_orders(self):
        with TemporaryDirectory() as data:
            env = dict(os.environ, PVZ_DATA=data, PVZ_DEMO="1", PVZ_QUIET="1")
            # The original packaged server creates the same schema as existing workspaces.
            subprocess.run([sys.executable, "-B", "-c",
                            "import server; server.bootstrap(); server.execute('/api/demo/run', 'dispatcher', {}, 'run')"],
                           cwd=APP, env=env, check=True, timeout=20)
            with closing(sqlite3.connect(Path(data) / "catalog.sqlite")) as registry:
                name = registry.execute("SELECT name FROM active").fetchone()[0]
            with closing(sqlite3.connect(Path(data) / name)) as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
                columns = ",".join(record[1] for record in db.execute("PRAGMA table_info(op_orders)"))
                read_orders = f"SELECT {columns} FROM op_orders ORDER BY id"
                before = db.execute(read_orders).fetchall()
                self.assertEqual(len(before), 10)

            with isolated_server(APP, data_dir=data, demo=False) as base:
                self.assertEqual(request(base, "/health/ready")["status"], "ready")
                report = request(base, PATH)
                migrated = row(report, "B")
                self.assertEqual(migrated["unique_orders"], 10)
                self.assertEqual(migrated["confidence"], "low")
                with self.assertRaises(HTTPError) as denied:
                    request(base, PATH, {"action": "surge"})
                with closing(denied.exception) as response:
                    self.assertEqual(response.code, 403)
                    self.assertEqual(json.load(response)["error"], "DEMO_DISABLED")
            with closing(sqlite3.connect(Path(data) / name)) as db:
                self.assertGreaterEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(db.execute(read_orders).fetchall(), before)
                saved = db.execute("""
                    SELECT demand_index, forecast_units, recalculated_at, region_id, locality_id FROM demand_estimates
                    WHERE sku='S' AND geography='zone' AND zone='B'
                """).fetchone()
                self.assertEqual(saved, (migrated["demand_index"], migrated["forecast_units"],
                                         report["recalculated_at"], migrated["region_id"], migrated["locality_id"]))

    def test_previous_demand_schema_preserves_selected_demo_history(self):
        with TemporaryDirectory() as data:
            with isolated_server(APP, data_dir=data) as base:
                request(base, PATH, {"action": "surge"})
                self.assertEqual(row(request(base, PATH), "B")["unique_orders"], 34)
            with closing(sqlite3.connect(Path(data) / "catalog.sqlite")) as registry:
                name = registry.execute("SELECT name FROM active").fetchone()[0]
            with closing(sqlite3.connect(Path(data) / name)) as db:
                columns = ",".join(record[1] for record in db.execute("PRAGMA table_info(demand_estimates)")
                                   if record[1] not in {"region_id", "locality_id"})
                db.executescript(f"""
                    CREATE TABLE old_estimates AS SELECT {columns} FROM demand_estimates WHERE sku<>'SMARTPHONE';
                    DROP TABLE demand_estimates;
                    ALTER TABLE old_estimates RENAME TO demand_estimates;
                    DELETE FROM demand_demo_orders WHERE sku='SMARTPHONE';
                    PRAGMA user_version=2;
                """)

            with isolated_server(APP, data_dir=data) as base:
                upgraded = request(base, PATH)
                previous = row(upgraded, "B")
                phone = row(upgraded, "B", sku="SMARTPHONE")
                self.assertEqual((previous["unique_orders"], previous["demand_index"]), (34, 77))
                self.assertEqual((phone["unique_orders"], phone["demand_index"]), (34, 77))
                self.assertEqual(phone["region_id"], "north")
            with isolated_server(APP, data_dir=data) as base:
                self.assertEqual(request(base, PATH), upgraded)


if __name__ == "__main__":
    unittest.main()
