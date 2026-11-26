"""Observed SKU demand and advisory replenishment in the shift database."""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from math import floor
import json

from common import instant
import desk
import geography
import operations as ops
import routing
from pickup_points import POINTS


WEEK = timedelta(days=7)
WEIGHTS = (1, .75, .5, .25)
OBSERVATION_DAYS = 7 * len(WEIGHTS)
WEIGHTED_DAYS = 7 * sum(WEIGHTS)
FORECAST_DAYS = 14
REFERENCE_ORDERS_PER_DAY = 2
MIN_PLACEMENT_INDEX = 50

# Counts from the newest week to the oldest. Both histories use the same clock.
BASE_HISTORY = {
    ("S", "B"): (2, 2, 2, 0),
    ("S", "C"): (12, 10, 8, 6),
    ("S", "D"): (1, 0, 0, 0),
    ("S", "J"): (3, 3, 2, 2),
    ("M", "E"): (3, 2, 1, 0),
    ("SMARTPHONE", "B"): (2, 2, 2, 0),
    ("SMARTPHONE", "D"): (1, 0, 0, 0),
}
EXTRA_B = (14, 8, 4, 2)


def set_demo_history(db, surge, *, seed_only=False):
    anchor = instant(desk.START)
    series = [(sku, point, counts, "baseline", "ISSUED")
              for (sku, point), counts in BASE_HISTORY.items()]
    series.extend((sku, "B", EXTRA_B, "extra", "ISSUED" if surge else "CANCELLED")
                  for sku in ("S", "SMARTPHONE"))
    statement = "INSERT INTO demand_demo_orders(id, sku, zone, at, status) VALUES (?, ?, ?, ?, ?)"
    conflict = "DO NOTHING" if seed_only else "DO UPDATE SET status=excluded.status"
    db.executemany(statement + " ON CONFLICT(id) " + conflict, (
        (f"{series_id}-{sku}-{point}-{week}-{i}", sku, point,
         (anchor - week * WEEK - timedelta(days=3)).isoformat(), status)
        for sku, point, counts, series_id, status in series
        for week, count in enumerate(counts) for i in range(count)
    ))


def migrate(db, demo):
    """Add or upgrade demand storage in the caller's write transaction."""
    estimate_columns = {row[1] for row in db.execute("PRAGMA table_info(demand_estimates)")}
    db.execute("""
        CREATE TABLE IF NOT EXISTS demand_demo_orders (
            id TEXT PRIMARY KEY, sku TEXT NOT NULL, zone TEXT NOT NULL,
            at TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('ISSUED', 'CANCELLED'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS demand_estimates (
            sku TEXT NOT NULL, geography TEXT NOT NULL CHECK(geography IN ('region', 'zone')),
            region TEXT NOT NULL, zone TEXT NOT NULL,
            observed_from TEXT NOT NULL, observed_to TEXT NOT NULL,
            unique_orders INTEGER NOT NULL, active_weeks INTEGER NOT NULL,
            weighted_orders REAL NOT NULL, demand_index INTEGER CHECK(demand_index BETWEEN 0 AND 100),
            forecast_units REAL, confidence TEXT NOT NULL CHECK(confidence IN ('low', 'medium', 'high')),
            forecast_days INTEGER NOT NULL,
            recalculated_at TEXT NOT NULL,
            region_id TEXT NOT NULL,
            locality_id TEXT,
            PRIMARY KEY (sku, geography, region_id, zone)
        )
    """)
    upgraded = bool(estimate_columns) and "region_id" not in estimate_columns
    if upgraded:
        db.execute("ALTER TABLE demand_estimates ADD COLUMN region_id TEXT NOT NULL DEFAULT ''")
        db.execute("ALTER TABLE demand_estimates ADD COLUMN locality_id TEXT")
    seed_demo = demo and not db.execute(
        "SELECT 1 FROM demand_demo_orders WHERE sku='SMARTPHONE' LIMIT 1"
    ).fetchone()
    if seed_demo:
        prior_surge = db.execute("""
            SELECT 1 FROM demand_demo_orders WHERE id LIKE 'extra-S-%' AND status='ISSUED' LIMIT 1
        """).fetchone()
        set_demo_history(db, surge=bool(prior_surge), seed_only=True)
    if not estimate_columns or upgraded or seed_demo:
        recalculate(db)
    if db.execute("PRAGMA user_version").fetchone()[0] < 2:
        db.execute("PRAGMA user_version=2")


def estimate(counts):
    orders = sum(counts.values())
    active_weeks = len(counts)
    weighted = sum(count * WEIGHTS[week] for week, count in counts.items())
    rate = weighted / WEIGHTED_DAYS
    if not orders:
        return 0, 0, 0, None, None, "low"
    support = min(orders / 8, 1) * min(active_weeks / 3, 1)
    index = floor(100 * min(rate / REFERENCE_ORDERS_PER_DAY, 1) * support + .5)
    confidence = "low"
    if orders >= 8 and active_weeks >= 2:
        confidence = "high" if orders >= 20 and active_weeks >= 3 else "medium"
    return orders, active_weeks, weighted, index, round(rate * FORECAST_DAYS, 2), confidence


def recalculate(db):
    end = instant(desk.get(db, "now"))
    start = end - timedelta(days=OBSERVATION_DAYS)
    recalculated_at = datetime.now(UTC).isoformat()
    skus = {row[0] for row in db.execute("""
        SELECT sku_id FROM op_lots UNION SELECT sku FROM demand_demo_orders
    """)}
    localities = geography.registry(db)
    regions = {locality["region_id"]: locality["region_name"] for locality in localities.values()}
    counts = defaultdict(Counter)
    # Each source has one canonical row per order. Scan and movement tables are event logs.
    orders = db.execute("""
        SELECT l.sku_id, o.destination, o.issued_at
        FROM op_orders o JOIN op_lots l ON l.id=o.lot_id
        WHERE o.issued_at IS NOT NULL AND o.status NOT IN ('CANCELLED', 'CANCELED')
        UNION ALL
        SELECT sku, zone, at FROM demand_demo_orders WHERE status='ISSUED'
    """)
    for sku, zone, at in orders:
        when = instant(at)
        if zone in localities and start < when <= end:
            week = (end - when) // WEEK
            region_id = localities[zone]["region_id"]
            counts[sku, region_id, zone][week] += 1
            counts[sku, region_id, ""][week] += 1
    geographies = [(region_id, "", None) for region_id in regions]
    geographies += [(locality["region_id"], zone, locality["id"]) for zone, locality in localities.items()]
    db.execute("DELETE FROM demand_estimates")
    db.executemany("""
        INSERT INTO demand_estimates (
            sku, geography, region, zone, observed_from, observed_to, unique_orders, active_weeks,
            weighted_orders, demand_index, forecast_units, confidence, forecast_days, recalculated_at,
            region_id, locality_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, ((sku, "zone" if zone else "region", regions[region_id], zone, start.isoformat(), end.isoformat(),
           *estimate(counts[sku, region_id, zone]), FORECAST_DAYS, recalculated_at, region_id, locality_id)
          for sku in sorted(skus) for region_id, zone, locality_id in geographies))
    desk.put(db, "demand_calculation", {"observed_from": start.isoformat(),
                                      "observed_to": end.isoformat(),
                                      "recalculated_at": recalculated_at})
    return {"recalculated_at": recalculated_at}


def zone_estimates(db, sku):
    """Read the latest saved SKU estimates at the shelf-placement level."""
    return {row["zone"]: dict(row) for row in db.execute(
        "SELECT * FROM demand_estimates WHERE sku=? AND geography='zone'", (sku,)
    )}


def lane_window(db, inventory, settings, zone):
    source = settings["source"]
    if zone == source:
        return None
    if zone != settings["destination"]:
        saved = db.execute("SELECT value FROM desk_meta WHERE key=?", ("lane-" + source + zone,)).fetchone()
        settings = json.loads(saved[0]) if saved else routing.default_settings(source, zone)
    return desk.effective_window(db, settings, inventory)


def transport_capacity(window, volume_l, mass_g, now):
    """Units that can use the existing shared route window and handling budgets."""
    if not window or not window["origin_open"] or not window["destination_open"]:
        return 0
    limits = [window["shared_slots"], window["shared_liters"], window["shared_grams"],
              window["origin_minutes"], window["destination_minutes"]]
    if any(value is None for value in limits):
        return 0
    slots, liters, grams, origin_minutes, destination_minutes = limits
    cutoff = window.get("shared_handoff_at")
    if cutoff:
        origin_minutes = min(origin_minutes, (instant(cutoff) - now).total_seconds() / 60)
    capacity = max(0, floor(min(slots, liters / volume_l, grams / mass_g,
                                origin_minutes / 1.8, destination_minutes / 2.2)))
    hours, reason = routing._schedule("shared", window, now, capacity * 1.8)
    return capacity if reason is None and hours <= FORECAST_DAYS * 24 else 0


def recommendation(estimate_row, local_stock, free_l, window, package, now):
    region = estimate_row["geography"] == "region"
    forecast = estimate_row["forecast_units"]
    volume_l, mass_g = package or (None, None)
    if window and window["destination_liters"] is not None:
        free_l = min(free_l, window["destination_liters"])
    shelf_units = floor(free_l / volume_l) if volume_l else None
    transport_units = transport_capacity(window, volume_l, mass_g, now) if volume_l and mass_g else None
    units = 0
    if region:
        reason = "Для размещения выберите зону ПВЗ."
    elif forecast is None:
        reason = "Нет выдач за период наблюдения."
    elif estimate_row["confidence"] == "low":
        reason = "Мало заказов или недель с выдачами."
    elif estimate_row["demand_index"] < MIN_PLACEMENT_INDEX:
        reason = f"Индекс ниже порога {MIN_PLACEMENT_INDEX} для локального размещения."
    elif package is None:
        reason = "Нужны объём и масса единицы SKU."
    elif floor(forecast) <= local_stock:
        reason = "Свободный запас покрывает прогноз."
    elif not shelf_units:
        reason = "На складе нет места для единицы SKU."
    elif not transport_units:
        reason = "Нет подходящего попутного окна для пополнения."
    else:
        need = floor(forecast) - local_stock
        units = min(need, shelf_units, transport_units)
        limits = [(need, "прогноз за вычетом запаса"), (shelf_units, "место на складе"),
                  (transport_units, "попутное окно")]
        reason = "Лимит пополнения — " + ", ".join(label for cap, label in limits if cap == units) + "."
    return {"units": None if region else units, "reason": reason,
            "on_hand": local_stock, "free_liters": free_l, "shelf_units": shelf_units,
            "transport_units": transport_units}


def report(db, demo):
    settings = desk.get(db, "settings")
    now = instant(desk.get(db, "now"))
    inventory = ops.snapshot(db)
    on_hand = Counter()
    packages = {}
    for sku, (dimensions, mass_g) in ops.PACKAGES.items():
        length, width, height = dimensions
        packages[sku] = (length * width * height / 1_000_000, mass_g)
    for lot in sorted(inventory["lots"], key=lambda item: (item["accepted_at"], item["id"])):
        sku = lot["sku_id"]
        for place, units in lot["positions"].items():
            point, _, status = place.partition(":")
            if status == "AVAILABLE":
                on_hand[sku, point] += units
        packages[sku] = (lot["volume_l"], lot["mass_g"])
    windows = {zone: lane_window(db, inventory, settings, zone) for zone in POINTS}
    localities = geography.registry(db)
    rows = []
    for row in db.execute("SELECT * FROM demand_estimates ORDER BY sku, region, geography, zone"):
        item = dict(row)
        zone = item["zone"]
        item["zone_name"] = POINTS[zone]["title"] if zone else None
        locality = localities.get(zone, {})
        item["locality_name"] = locality.get("name")
        item["locality_type"] = locality.get("type")
        item["recommendation"] = recommendation(
            item, on_hand[item["sku"], zone], desk.free_space(inventory, zone) if zone else None,
            windows.get(zone), packages.get(item["sku"]) if zone else None, now)
        rows.append(item)
    return {**desk.get(db, "demand_calculation"), "rows": rows, "demo_enabled": demo,
            "source": settings["source"], "forecast_days": FORECAST_DAYS}
