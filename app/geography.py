"""Settlement registry and order geography for the local shift."""

import operations as ops
import routing
from truck_routes import NETWORK, road_distance


NORTH = ("north", "Северная область")
SOUTH = ("south", "Южная область")
SETTLEMENTS = {
    "north-novoozersk": (*NORTH, "Новоозёрск", "city"),
    "north-raicentr": (*NORTH, "Райцентр", "town"),
    "north-ozernoe": (*NORTH, "Озёрное", "village"),
    "north-borovoe": (*NORTH, "Боровое", "hamlet"),
    "south-lugovaya": (*SOUTH, "Луговая", "hamlet"),
    "south-ozernoe": (*SOUTH, "Озёрное", "village"),
}
POINT_SETTLEMENTS = {
    **dict.fromkeys("ABEF", "north-novoozersk"),
    "C": "north-raicentr",
    "D": "north-ozernoe",
    "G": "north-borovoe",
    "J": "south-lugovaya",
    "K": "south-ozernoe",
}
SHIP_FROM = "seller_ship_from_pvz_id"
LOCALITY_FIELDS = ("id", "region_id", "region_name", "name", "type")

_original_order = ops.order
_original_snapshot = ops.snapshot
_original_event = ops.event
_original_bill = ops._bill
_original_rates = routing._rates
_original_fits = routing._fits


def migrate(db):
    """Install the catalog and backfill the only shipment point recorded by older workspaces."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS geo_settlements (
            id TEXT PRIMARY KEY, region_id TEXT NOT NULL, region_name TEXT NOT NULL,
            name TEXT NOT NULL, type TEXT NOT NULL CHECK(type IN ('city', 'town', 'village', 'hamlet'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS geo_pvz (
            point_id TEXT PRIMARY KEY,
            locality_id TEXT NOT NULL REFERENCES geo_settlements(id)
        )
    """)
    db.executemany("INSERT OR IGNORE INTO geo_settlements VALUES (?, ?, ?, ?, ?)",
                   ((key, *fields) for key, fields in SETTLEMENTS.items()))
    db.executemany("INSERT OR IGNORE INTO geo_pvz VALUES (?, ?)", POINT_SETTLEMENTS.items())
    if not has_order_locations(db):
        db.execute("ALTER TABLE op_orders ADD COLUMN seller_ship_from_pvz_id TEXT")
        db.execute("UPDATE op_orders SET seller_ship_from_pvz_id=source")


def has_order_locations(db):
    return any(row["name"] == SHIP_FROM for row in db.execute("PRAGMA table_info(op_orders)"))


def registry(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='geo_pvz'").fetchone():
        # The packaged service can advance preview orders before migration of a new workspace.
        return {point: dict(zip(LOCALITY_FIELDS, (key, *SETTLEMENTS[key])))
                for point, key in POINT_SETTLEMENTS.items()}
    return {row["point_id"]: {k: row[k] for k in LOCALITY_FIELDS}
            for row in db.execute("""
                SELECT p.point_id, s.* FROM geo_pvz p JOIN geo_settlements s ON s.id=p.locality_id
            """)}


def route_scope(start, finish):
    if not start or not finish:
        return "unknown"
    if start["id"] == finish["id"]:
        return "local"
    if start["type"] != "city" or finish["type"] != "city":
        return "rural"
    return "intercity"


def describe(order, localities):
    seller_point = order.get(SHIP_FROM, order["source"])
    buyer_point = order["destination"]
    stock_point = order["source"]
    seller, buyer, stock = (localities.get(point) for point in (seller_point, buyer_point, stock_point))
    if seller is None or buyer is None:
        relation = "unknown"
        missing = [label for item, label in ((seller, "точки отгрузки"), (buyer, "ПВЗ выдачи")) if item is None]
        reason = "В справочнике нет населённого пункта для " + " и ".join(missing) + "."
    elif seller["id"] == buyer["id"]:
        relation = "same_locality"
        reason = f"Точка отгрузки и ПВЗ выдачи находятся в одном населённом пункте — {seller['name']} ({seller['region_name']})."
    else:
        relation = "different_localities"
        reason = (f"Отгрузка продавца — {seller['name']} ({seller['region_name']}), "
                  f"выдача — {buyer['name']} ({buyer['region_name']}).")
    scope = route_scope(stock, buyer)
    km = road_distance(stock_point, buyer_point)
    block = None
    if stock_point != buyer_point:
        if relation == "unknown" or scope == "unknown":
            block = "UNKNOWN_GEOGRAPHY"
        elif km is None:
            block = "NO_ROAD_ROUTE"
    return {"relation": relation, "reason": reason, "route_scope": scope, "road_km": km,
            "direct_block": block, "seller_ship_from": {"point_id": seller_point, "locality": seller},
            "buyer_pickup": {"point_id": buyer_point, "locality": buyer},
            "stock_start": {"point_id": stock_point, "locality": stock}}


def find_stock_source(db, lot, requested):
    if requested is not None:
        return ops._point(requested)
    origin = lot["pvz_id"]
    rows = db.execute("SELECT DISTINCT place FROM op_stock WHERE lot_id=? ORDER BY place", (lot["id"],))
    available = {place.removesuffix(":AVAILABLE") for place, in rows if place.endswith(":AVAILABLE")}
    if origin in available:
        return origin
    return min(available & ops.POINT_CAPACITY.keys(), default=origin)


def reserve_at(db, body, lot, source, destination):
    """Use the original reservation lifecycle for a relocated unit or an on-site pickup."""
    if ops._integer(body.get("quantity", 1), "quantity") != 1:
        ops._bad("quantity (одна единица на заказ)")
    if "expected_version" in body:
        ops._check_version(lot, body)
    at = ops._utc(body["_now"])
    if at < lot["accepted_at"]:
        ops._conflict("BEFORE_RECEIPT", "Партия ещё не принята")
    original = ops._utc(body.get("original_promised_at", body.get("promised_at")))
    promise = ops._utc(body.get("selected_promised_at", body.get("promised_at")))
    consent = body.get("consent", False)
    if type(consent) is not bool or promise < original or (not consent and promise != original):
        ops._bad("consent")
    if original <= at:
        ops._bad("original_promised_at")
    oid = ops._string(body.get("order_id", ops._id("O")), "order_id")
    if db.execute("SELECT 1 FROM op_orders WHERE id=?", (oid,)).fetchone():
        ops._conflict("ORDER_EXISTS", "Заказ с таким ID уже есть")
    unit = db.execute("SELECT * FROM op_stock WHERE lot_id=? AND place=? ORDER BY id LIMIT 1",
                      (lot["id"], source + ":AVAILABLE")).fetchone()
    if unit is None:
        ops._conflict("NO_STOCK", "Свободных единиц этой партии нет в выбранном ПВЗ")
    price = ops._integer(body.get("delivery_price", 0), "delivery_price", 0)
    db.execute("""INSERT INTO op_orders(id,lot_id,unit_id,cycle,source,destination,created_at,
                  promised_at,original_promised_at,consent,buyer_delivery_price,status,version,last_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,'RESERVED',1,?)""",
               (oid, lot["id"], unit["id"], unit["cycle"], source, destination, at, promise,
                original, int(consent), price, at))
    eid = ops._log(db, "RESERVED", at, lot["id"], oid, request_id=body.get("_request_id"))
    ops._move(db, eid, unit, source + ":RESERVED", at)
    db.execute("UPDATE op_lots SET version=version+1 WHERE id=?", (lot["id"],))
    return dict(id=oid, order_id=oid, lot_id=lot["id"], unit_id=unit["id"], status="RESERVED",
                version=1, original_promised_at=original, promised_at=promise)


def order(db, body):
    lot = ops._lot(db, body.get("lot_id"))
    source = find_stock_source(db, lot, body.get("stock_source_pvz_id"))
    destination = ops._point(body.get("pvz_id"))
    if source == lot["pvz_id"] and source != destination:
        result = _original_order(db, body)
    else:
        result = reserve_at(db, body, lot, source, destination)
    seller_point = body.get(SHIP_FROM, lot["pvz_id"])
    if has_order_locations(db):
        db.execute("UPDATE op_orders SET seller_ship_from_pvz_id=? WHERE id=?", (seller_point, result["id"]))
    locations = {"source": source, "destination": destination, SHIP_FROM: seller_point}
    return {**result, **locations, "geography": describe(locations, registry(db))}


def bill(db, unit, lot, until, profile, request_id=None):
    place = unit["place"] if "place" in unit.keys() else ops._unit(db, unit["id"])["place"]
    point = place.partition(":")[0]
    if point in POINT_SETTLEMENTS and point != lot["pvz_id"]:
        lot = {**lot, "pvz_id": point}
    return _original_bill(db, unit, lot, until, profile, request_id)


def event(db, body):
    result = _original_event(db, body)
    if body.get("event_type") != "ASSEMBLED":
        return result
    order = ops._order(db, result["order_id"])
    point = order["source"]
    if point != order["destination"]:
        return result
    at, profile = order["last_at"], body["_profile"]
    unit, lot = ops._unit(db, order["unit_id"]), ops._lot(db, order["lot_id"])
    ops._bill(db, unit, lot, at, profile, body.get("_request_id"))
    db.execute("UPDATE op_units SET storage_start=NULL WHERE id=?", (unit["id"],))
    eid = ops._log(db, "LOCAL_READY", at, lot["id"], order["id"], request_id=body.get("_request_id"))
    ops._move(db, eid, unit, point + ":READY", at)
    db.execute("""UPDATE op_orders SET status='READY_FOR_PICKUP', mode='LOCAL_PICKUP',
                  ready_at=?, profile=? WHERE id=?""", (at, profile, order["id"]))
    return {**result, "status": "READY_FOR_PICKUP", "movements": [*result["movements"],
            {"lot_id": lot["id"], "from": unit["place"], "to": point + ":READY", "quantity": 1}]}


def snapshot(db):
    result = _original_snapshot(db)
    localities = registry(db)
    for item in result["orders"]:
        item.setdefault(SHIP_FROM, item["source"])
        item["geography"] = describe(item, localities)
    for lot in result["lots"]:
        places = lot["positions"]
        available = {point: places[point + ":AVAILABLE"] for point in POINT_SETTLEMENTS
                     if places.get(point + ":AVAILABLE")}
        reserved = {point: places.get(point + ":RESERVED", 0) + places.get(point + ":ASSEMBLED", 0)
                    for point in POINT_SETTLEMENTS}
        lot.update(available_by_pvz=available, available=sum(available.values()),
                   reserved_by_pvz={point: quantity for point, quantity in reserved.items() if quantity},
                   reserved=sum(reserved.values()))
    return result


def rates(mode, settings, lost, start, pack_minutes):
    direct = mode != routing.HUB
    if direct:
        km = road_distance(settings["source"], settings["destination"])
        key = routing.PREFIX[mode] + "_ready_hours"
        hours = settings.get(key)
        if km is not None and routing._number(hours):
            settings = {**settings, key: max(hours, km / NETWORK["speedKmh"])}
    return {**_original_rates(mode, settings, lost, start, pack_minutes), "direct": direct}


def fits(item, rate, used, start, deadline):
    if rate["direct"] and (block := item.get("geography", {}).get("direct_block")):
        return block
    return _original_fits(item, rate, used, start, deadline)


def connect_shift():
    ops.order = order
    ops.snapshot = snapshot
    ops.event = event
    ops._bill = bill
    routing._rates = rates
    routing._fits = fits
