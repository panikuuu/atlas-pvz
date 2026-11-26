"""Compare and execute placement of free physical units."""

from collections import Counter
from hashlib import sha256
import json
from math import isfinite
from uuid import uuid4

import demand
import desk
import operations as ops
import routing
from common import Problem, instant
from pickup_points import POINTS
from truck_routes import NETWORK, RATES, road_distance


# Money is in kopecks. Rates, thresholds and transport assumptions are per shift.
DEFAULTS = {
    "min_index": 50, "expensive_min_index": 65, "expensive_cost": 1_000_000,
    "min_confidence_level": 1, "expensive_min_confidence_level": 2,
    "confidence_low": .05, "confidence_medium": .65, "confidence_high": 1,
    "hub_capture": .10, "commission": .15, "local_sale_delivery": 0,
    "hub_sale_delivery": RATES["cityHub"],
    "pvz_storage": 80, "pvz_space": 14, "hub_storage": 35, "hub_space": 8,
    "annual_capital": .18, "obsolescence": .02, "min_improvement": 100,
    "km_cost": RATES["km"], "stop_minute": RATES["stopMinute"], "handling_minutes": 4,
    "origin_handling_minutes": 1.8, "destination_handling_minutes": 2.2,
    "hub_transfer_fixed": 2200, "hub_transfer_slots": 120, "hub_transfer_liters": 720,
    "hub_transfer_grams": 216000, "hub_transfer_wait_hours": 24,
}
FRACTIONS = {"confidence_low", "confidence_medium", "confidence_high", "hub_capture",
             "commission", "annual_capital", "obsolescence"}
CONFIDENCE_LEVEL = {"low": 0, "medium": 1, "high": 2}
ACTIVE = ("RESERVED", "IN_TRANSIT")
EVENT = {"confirm": "PLACEMENT_RESERVED", "send": "PLACEMENT_SENT",
         "receive": "PLACEMENT_RECEIVED", "cancel": "PLACEMENT_CANCELLED"}


def migrate(db):
    db.execute("""
        CREATE TABLE IF NOT EXISTS stock_placements (
            id TEXT PRIMARY KEY, lot_id TEXT NOT NULL REFERENCES op_lots(id),
            unit_id TEXT NOT NULL REFERENCES op_units(id), source TEXT NOT NULL,
            destination TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL
            CHECK(status IN ('RESERVED','IN_TRANSIT','RECEIVED','CANCELLED')),
            economics TEXT NOT NULL
        )
    """)
    db.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS stock_placements_active_unit
        ON stock_placements(unit_id) WHERE status IN ('RESERVED','IN_TRANSIT')
    """)


def settings(db):
    row = db.execute("SELECT value FROM desk_meta WHERE key='stock_placement_settings'").fetchone()
    return {**DEFAULTS, **(json.loads(row[0]) if row else {})}


def configure(db, changes):
    values = settings(db)
    for key, value in changes.items():
        limit = 1 if key in FRACTIONS else 100 if key.endswith("index") else 1_000_000_000
        if key not in DEFAULTS or type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= limit:
            raise Problem(422, "INVALID_PLACEMENT_SETTING", f"Проверьте параметр {key}.")
        if key.endswith("confidence_level") and value not in CONFIDENCE_LEVEL.values():
            raise Problem(422, "INVALID_PLACEMENT_SETTING", "Уровень уверенности должен быть 0, 1 или 2.")
        values[key] = value
    if not values["confidence_low"] <= values["confidence_medium"] <= values["confidence_high"]:
        raise Problem(422, "INVALID_PLACEMENT_SETTING", "Вес уверенности должен возрастать.")
    desk.put(db, "stock_placement_settings", values)
    return {"settings": values}


def stock_place(point):
    return "HUB" if point == "HUB" else point + ":AVAILABLE"


def reserved_place(point):
    return point + ":PLACEMENT_RESERVED"


def transfer_rows(db):
    return [dict(row) for row in db.execute("""
        SELECT t.*, l.sku_id AS sku, l.volume_l, l.mass_g
        FROM stock_placements t JOIN op_lots l ON l.id=t.lot_id ORDER BY t.rowid DESC
    """)]


def transfer_payload(db, transfer):
    row = dict(transfer)
    row["economics"] = json.loads(row["economics"])
    row["journal"] = [dict(event) for event in db.execute("""
        SELECT at, id AS event_id, event_type AS action
        FROM op_events WHERE dispatch_id=? ORDER BY rowid
    """, (row["id"],))]
    return row


class Placement:
    def __init__(self, db):
        self.db = db
        self.settings = settings(db)
        self.inventory = ops.snapshot(db)
        self.lots = {lot["id"]: lot for lot in self.inventory["lots"]}
        self.now = instant(desk.get(db, "now"))
        self.window = desk.get(db, "settings")
        self.transfers = transfer_rows(db)
        self.pending = [row for row in self.transfers if row["status"] in ACTIVE]
        self.available = Counter()
        self.incoming = Counter()
        self.incoming_liters = Counter()
        self.customer_liters = Counter()
        self.estimates = {}
        for lot in self.lots.values():
            for point in (*POINTS, "HUB"):
                self.available[lot["sku_id"], point] += lot["positions"].get(stock_place(point), 0)
        for row in self.pending:
            self.incoming[row["sku"], row["destination"]] += 1
            self.incoming_liters[row["destination"]] += row["volume_l"]
        for order in self.inventory["orders"]:
            if order["status"] in ("ASSIGNED", "IN_TRANSIT"):
                self.customer_liters[order["destination"]] += order["volume_l"]

    def coverage(self, sku, point, source):
        return self.available[sku, point] + self.incoming[sku, point] - int(point == source)

    def destination_space(self, point, exclude=None):
        booked = self.incoming_liters[point] - (exclude["volume_l"] if exclude else 0)
        return max(0, desk.free_space(self.inventory, point) - self.customer_liters[point] - booked)

    def transport(self, source, point, lot, days, exclude=None):
        km = road_distance(source, point)
        if km is None:
            return {}
        cfg = self.settings
        bookings = [row for row in self.pending if row["id"] != (exclude or {}).get("id")]
        liters, grams = lot["volume_l"], lot["mass_g"]
        if "HUB" in {source, point}:
            hub_leg = [row for row in bookings if row["source"] == source and row["destination"] == point]
            hours = cfg["hub_transfer_wait_hours"] + km / NETWORK["speedKmh"]
            if (hours > days * 24 or cfg["hub_transfer_slots"] < len(hub_leg) + 1
                    or cfg["hub_transfer_liters"] < liters + sum(row["volume_l"] for row in hub_leg)
                    or cfg["hub_transfer_grams"] < grams + sum(row["mass_g"] for row in hub_leg)):
                return {}
            return {"hub_leg": round(cfg["hub_transfer_fixed"] + km * cfg["km_cost"])}

        if (source, point) == (self.window["source"], self.window["destination"]):
            lane = self.window
        else:
            saved = self.db.execute("SELECT value FROM desk_meta WHERE key=?", ("lane-" + source + point,)).fetchone()
            lane = json.loads(saved[0]) if saved else routing.default_settings(source, point)
        window = desk.effective_window(self.db, lane, self.inventory)
        if not window["origin_open"] or not window["destination_open"]:
            return {}
        if window["destination_liters"] is None or window["destination_liters"] < liters:
            return {}
        origin_load = sum(row["source"] == source for row in bookings)
        destination_load = sum(row["destination"] == point for row in bookings)
        origin_minutes = cfg["origin_handling_minutes"] * (origin_load + 1)
        destination_minutes = cfg["destination_handling_minutes"] * (destination_load + 1)
        if ((window["origin_minutes"] or 0) < origin_minutes
                or (window["destination_minutes"] or 0) < destination_minutes):
            return {}
        lane_bookings = [row for row in bookings if row["source"] == source and row["destination"] == point]
        costs = {
            "shared": None if window["detour_km"] is None or window["detour_minutes"] is None else
            window["detour_km"] * cfg["km_cost"] + window["detour_minutes"] * cfg["stop_minute"],
            "dedicated": window["roundtrip_fixed"],
            "hub": window["hub_per_unit"],
        }
        modes = {}
        for mode, cost in costs.items():
            booked = [row for row in lane_bookings if row["mode"] == mode]
            needs = (len(booked) + 1, liters + sum(row["volume_l"] for row in booked),
                     grams + sum(row["mass_g"] for row in booked))
            capacity = (window.get(f"{mode}_{unit}") for unit in ("slots", "liters", "grams"))
            if cost is None or any(limit is None or limit < need for limit, need in zip(capacity, needs)):
                continue
            hours, error = routing._schedule(mode, window, self.now, origin_minutes)
            if error is None and hours <= days * 24:
                modes[mode] = round(cost + cfg["handling_minutes"] * cfg["stop_minute"])
        return modes

    def option(self, lot, source, action, point, estimates):
        cfg = self.settings
        sku = lot["sku_id"]
        estimate = estimates.get(point, {})
        index, forecast = estimate.get("demand_index"), estimate.get("forecast_units")
        confidence = estimate.get("confidence", "low")
        days = estimate.get("forecast_days", demand.FORECAST_DAYS)
        other = self.coverage(sku, point, source)
        expensive = lot["cost_price"] >= cfg["expensive_cost"]
        threshold = cfg["expensive_min_index"] if expensive else cfg["min_index"]
        min_confidence = cfg["expensive_min_confidence_level"] if expensive else cfg["min_confidence_level"]
        confirmed = (index is not None and index >= threshold
                     and CONFIDENCE_LEVEL[confidence] >= min_confidence
                     and int(forecast or 0) > other)

        if point == "HUB":
            unmet = sum(max(0, (row["forecast_units"] or 0) - self.coverage(sku, zone, source))
                        * cfg["confidence_" + row["confidence"]] for zone, row in estimates.items())
            potential = cfg["hub_capture"] * unmet - other
        else:
            potential = max(0, (forecast or 0) - other) * cfg["confidence_" + confidence]
        sales = min(1, max(0, potential))
        delivery = cfg["hub_sale_delivery"] if point == "HUB" else cfg["local_sale_delivery"]
        margin = lot["sale_price"] * (1 - cfg["commission"]) - lot["cost_price"] - delivery
        benefit = round(sales * margin)
        place = "hub" if point == "HUB" else "pvz"
        costs = {
            "storage": round(cfg[place + "_storage"] * days * lot["volume_l"]),
            "space": round(cfg[place + "_space"] * days * lot["volume_l"]),
            "capital": round(lot["cost_price"] * cfg["annual_capital"] * days / 365),
            "obsolescence": round(lot["cost_price"] * cfg["obsolescence"] * (1 - sales)),
            "transport": 0,
        }
        mode, reason = None, None
        if action != "keep":
            modes = self.transport(source, point, lot, days)
            if modes:
                mode = min(modes, key=modes.get)
                costs["transport"] = modes[mode]
            if action == "relocate" and not confirmed:
                reason = "Локальный индекс, уверенность или непокрытый прогноз ниже порога."
            elif action == "relocate" and self.destination_space(point) + 1e-8 < lot["volume_l"]:
                reason = "На целевом ПВЗ не хватает свободного места."
            elif mode is None:
                reason = "Нет подходящего окна перевозки с доступными местами, объёмом и массой."
        if reason is None:
            reason = ("Хранение на текущем месте." if action == "keep" else
                      "Хаб обслуживает часть непокрытого спроса сети." if action == "hub" else
                      "Подтверждённый прогноз зоны превышает доступный и ожидаемый остаток.")
        eligible = action == "keep" or (mode is not None and (action == "hub" or
                   (confirmed and self.destination_space(point) + 1e-8 >= lot["volume_l"])))
        return dict(action=action, point=point, demand_index=index, forecast_units=forecast,
                    forecast_days=days, confidence=confidence, expected_sales=round(sales, 4),
                    benefit=benefit, costs=costs, net=benefit - sum(costs.values()) if eligible else None,
                    eligible=eligible, reason=reason, mode=mode, available_and_incoming=other)

    def row(self, lot, source):
        available = lot["positions"].get(stock_place(source), 0)
        if not available:
            return None
        if lot["sku_id"] not in self.estimates:
            self.estimates[lot["sku_id"]] = demand.zone_estimates(self.db, lot["sku_id"])
        estimates = self.estimates[lot["sku_id"]]
        keep = self.option(lot, source, "keep", source, estimates)
        options = [keep]
        if source != "HUB":
            options.append(self.option(lot, source, "hub", "HUB", estimates))
        options.extend(self.option(lot, source, "relocate", point, estimates) for point in POINTS if point != source)
        best = max((item for item in options if item["eligible"]), key=lambda item: item["net"])
        difference = best["net"] - keep["net"]
        if best is keep or difference <= self.settings["min_improvement"]:
            best = keep
            reason = "Оставить до пересмотра. Выгода доступных перемещений не превышает порог."
        else:
            reason = "Этот вариант даёт наибольшую ожидаемую выгоду после всех расходов."
        result = dict(lot_id=lot["id"], sku=lot["sku_id"], source=source, available=available,
                      version=lot["version"], recommendation=dict(action=best["action"], point=best["point"],
                          reason=reason, improvement=best["net"] - keep["net"]), options=options)
        evidence = {**result, "settings": self.settings, "estimates": estimates, "now": self.now.isoformat()}
        result["fingerprint"] = sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        return result

    def report(self):
        rows = [row for lot in self.lots.values() for point in (*POINTS, "HUB")
                if (row := self.row(lot, point))]
        return {"settings": self.settings, "rows": rows,
                "transfers": [transfer_payload(self.db, row) for row in self.transfers]}


def report(db):
    return Placement(db).report()


def conflict(message):
    raise Problem(409, "PLACEMENT_CONFLICT", message)


def confirm(db, body, placement):
    lot = placement.lots.get(body["lot_id"])
    source = body["source"]
    proposal = placement.row(lot, source) if lot else None
    if not proposal or proposal["fingerprint"] != body["fingerprint"]:
        conflict("Остаток, прогноз или условия изменились. Обновите расчёт.")
    selected = proposal["recommendation"]
    if selected["action"] == "keep":
        conflict("Перемещение не рекомендовано по текущим условиям.")
    option = next(row for row in proposal["options"] if row["action"] == selected["action"]
                  and row["point"] == selected["point"])
    unit = db.execute("SELECT * FROM op_stock WHERE lot_id=? AND place=? ORDER BY id LIMIT 1",
                      (lot["id"], stock_place(source))).fetchone()
    if unit is None:
        conflict("Свободная единица на исходной точке отсутствует.")
    transfer_id = "P-" + uuid4().hex[:16]
    db.execute("INSERT INTO stock_placements VALUES(?,?,?,?,?,?,'RESERVED',?)",
               (transfer_id, lot["id"], unit["id"], source, selected["point"],
                option["mode"], json.dumps(option, ensure_ascii=False)))
    return transfer_id, unit, reserved_place(source), "RESERVED"


def advance(db, body, placement):
    action, transfer_id = body["action"], body["transfer_id"]
    transfer = next((row for row in placement.pending if row["id"] == transfer_id), None)
    if not transfer:
        conflict("Перемещение отсутствует или уже завершено.")
    source, point, status = transfer["source"], transfer["destination"], transfer["status"]
    unit = ops._unit(db, transfer["unit_id"])
    lot = placement.lots[transfer["lot_id"]]
    if action == "receive" and status == "IN_TRANSIT" and unit["place"] == "PLACEMENT_IN_TRANSIT":
        if point != "HUB":
            if placement.destination_space(point, transfer) + 1e-8 < lot["volume_l"]:
                conflict("В ПВЗ пока нет места для приёмки этой единицы.")
            ops._capacity(db, point, lot["volume_l"])
        db.execute("UPDATE op_units SET storage_start=?, billed_days=0 WHERE id=?",
                   (None if point == "HUB" else placement.now.isoformat(), unit["id"]))
        return transfer_id, unit, stock_place(point), "RECEIVED"
    if status != "RESERVED" or unit["place"] != reserved_place(source):
        conflict("Операция недоступна на текущем этапе перемещения.")
    if action == "cancel":
        return transfer_id, unit, stock_place(source), "CANCELLED"
    if action != "send":
        conflict("Сначала подтвердите отправку со склада.")
    days = json.loads(transfer["economics"])["forecast_days"]
    if (point in POINTS and placement.destination_space(point, transfer) + 1e-8 < lot["volume_l"]
            or transfer["mode"] not in placement.transport(source, point, lot, days, exclude=transfer)):
        conflict("Окно перевозки или место приёмки больше недоступны.")
    ops._bill(db, unit, {**lot, "pvz_id": source}, placement.now.isoformat(), desk.get(db, "profile"),
              desk.REQUEST_ID.get())
    db.execute("UPDATE op_units SET storage_start=NULL, billed_days=0 WHERE id=?", (unit["id"],))
    return transfer_id, unit, "PLACEMENT_IN_TRANSIT", "IN_TRANSIT"


def command(db, body):
    action = body["action"]
    if action == "configure":
        return configure(db, body["settings"])
    placement = Placement(db)
    handler = confirm if action == "confirm" else advance
    transfer_id, unit, destination, status = handler(db, body, placement)
    event = ops._log(db, EVENT[action], placement.now.isoformat(), unit["lot_id"],
                     dispatch_id=transfer_id, request_id=desk.REQUEST_ID.get())
    ops._move(db, event, unit, destination, placement.now.isoformat())
    db.execute("UPDATE stock_placements SET status=? WHERE id=?", (status, transfer_id))
    db.execute("UPDATE op_lots SET version=version+1 WHERE id=?", (unit["lot_id"],))
    row = next(row for row in transfer_rows(db) if row["id"] == transfer_id)
    return {"transfer": transfer_payload(db, row)}
