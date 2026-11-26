"""A reproducible end-to-end demo using normal shift operations."""

from collections import Counter
from datetime import timedelta
import json
from uuid import uuid4

from common import Problem, instant
import demand
import desk
import fleet
import operations as ops


# Each item defines one lot, its origin, the customer pickup point and the quantity sold.
LANES = (
    ("RELAY", "A", "B", "S", 10, 10),
    ("CITY", "F", "E", "S", 8, 8),
    ("RURAL", "G", "D", "S", 8, 8),
    ("SOUTH", "B", "J", "S", 8, 8),
    ("HUB", "K", "J", "M", 1, 1),
    ("PHONE", "D", "D", "SMARTPHONE", 2, 1),
)
VEHICLES = (
    ("М1", "A", "C", 540, 625),
    ("М2", "C", "B", 620, 710),
    ("М3", "F", "E", 600, 695),
    ("М4", "G", "D", 645, 865),
    ("М5", "B", "J", 720, 915),
)
LABELS = (
    "Принять партии в ПВЗ",
    "Создать заказы и собрать посылки",
    "Рассчитать парк и закрепить заказы",
    "Погрузить и передать в буфер",
    "Доставить в ПВЗ и выдать",
    "Обработать возврат и долгое хранение",
)


def event(db, order_id, kind, reason=None):
    order = ops._order(db, order_id)
    point = order["source"] if kind in {"ASSEMBLED", "HANDED_OVER", "RETURN_RECEIVED"} else order["destination"]
    return ops.event(db, desk.ctx(db, {
        "order_id": order_id, "event_type": kind, "pvz_id": point,
        "expected_version": order["version"], "quantity": 1, **({"reason": reason} if reason else {}),
    }))


def receive(db):
    now = instant(desk.get(db, "now"))
    desk.put(db, "profile", "pilot")
    for key, source, _, sku, quantity, _ in LANES:
        body = {"lot_id": "UD-" + key, "sku_id": sku, "pvz_id": source, "quantity": quantity}
        if sku == "SMARTPHONE":
            body.update(sale_price=9_000_000, cost_price=7_500_000)
        if key == "HUB":
            # Fits the hub baseline, but exceeds the available load of a demo vehicle.
            body.update(dimensions_mm=[600, 300, 300], mass_g=35000)
        ops.receipt(db, desk.ctx(db, body))
    ops.receipt(db, desk.ctx(db, {
        "lot_id": "UD-AGED", "sku_id": "S", "pvz_id": "C", "quantity": 1,
        "occurred_at": (now - timedelta(days=30)).isoformat(), "storage_days": 30,
    }))


def reserve(db):
    now = instant(desk.get(db, "now"))
    for key, source, destination, _, _, orders in LANES:
        due = now + timedelta(days=2) if key == "HUB" else now + timedelta(hours=7)
        for index in range(1, orders + 1):
            order_id = f"UD-{key}-{index:02d}"
            lot = ops._lot(db, "UD-" + key)
            ops.order(db, desk.ctx(db, {
                "order_id": order_id, "lot_id": lot["id"], "quantity": 1, "pvz_id": destination,
                "promised_at": due.isoformat(), "expected_version": lot["version"],
                **({"seller_ship_from_pvz_id": "A"} if key == "PHONE" else {}),
            }))
            event(db, order_id, "ASSEMBLED")
            if source == destination:
                event(db, order_id, "ISSUED")


def prepare_plan(db, progress, day, calculate, confirm_day):
    trucks = [{"id": key, "start": source, "end": destination, "start_min": start,
               "end_min": end, "liters": 40, "kg": 30, "planned": True}
              for key, source, destination, start, end in VEHICLES]
    options = {"scenario": "live", "trucks": trucks, "prices": {"hub_city": 110}}
    plan = calculate(db, options)
    if not plan["economics"]["relayed_units"]:
        raise Problem(409, "DEMO_PLAN_CHANGED", "Условия дня изменены, передача между машинами недоступна.")
    day = confirm_day(db, {**plan["request"], "fingerprint": plan["fingerprint"]}, day)
    progress["fleet_id"] = day["id"]
    for batch in day["economics"]["hub_remaining"]:
        per_order = fleet.estimate_hub(batch, day["prices"]) // batch["qty"]
        ids = [order["id"] for order in batch["orders"]]
        dispatch_id = "T-HUB-" + uuid4().hex[:12]
        manifest = {
            "id": dispatch_id, "order_ids": ids, "mode": "HUB", "quote_id": None,
            "carrier_cost": per_order * len(ids), "created_at": desk.get(db, "now"), "window_id": "fleet",
        }
        for oid in ids:
            ops.attach(db, oid, dispatch_id, "HUB", per_order, day["request"]["contract"], desk.get(db, "now"), desk.REQUEST_ID.get())
        db.execute("INSERT INTO manifests VALUES(?,?)", (dispatch_id, desk.encode(manifest)))
    return day


def advance_fleet(db, day, advance, stop_at_transfer=False):
    if stop_at_transfer and any(entry["kind"] == "relay_drop" for entry in day["journal"]):
        return day
    for truck in day["trucks"]:
        if truck["status"] == "PLANNED":
            day = advance(db, day, {"action": "start", "day_id": day["id"], "version": day["version"], "truck": truck["id"]})
    while day["status"] != "DONE":
        candidates = []
        for truck in day["trucks"]:
            if truck["status"] == "DONE":
                continue
            stop = truck["stops"][truck["cursor"]]
            operation = next((item for item in stop["events"] if not item["done"]), None)
            if operation and operation["kind"] == "relay_pickup" and day["custody"][operation["batch"]]["kind"] != "relay":
                continue
            candidates.append((operation["at"] if operation else stop["leave"], truck["id"], operation))
        if not candidates:
            raise Problem(409, "DEMO_RELAY_BLOCKED", "Проверьте порядок операций передачи.")
        _, truck_id, operation = min(candidates, key=lambda item: item[:2])
        body = {"action": "next", "day_id": day["id"], "version": day["version"], "truck": truck_id}
        if operation:
            body.update(action="scan", batch=operation["batch"], operation=operation["kind"])
        day = advance(db, day, body)
        if stop_at_transfer and operation and operation["kind"] == "relay_drop":
            return day
    return day


def deliver(db, day, advance):
    hub_ids = [order["id"] for batch in day["economics"]["hub_remaining"] for order in batch["orders"]]
    for oid in hub_ids:
        if ops._order(db, oid)["status"] == "ASSIGNED":
            event(db, oid, "HANDED_OVER")
            if oid == "UD-HUB-01":
                event(db, oid, "INCIDENT", "Перевозчик · задержана одна посылка через хаб")
    day = advance_fleet(db, day, advance)
    for order in ops.snapshot(db)["orders"]:
        if order["status"] == "READY_FOR_PICKUP":
            event(db, order["id"], "ISSUED")
    if hub_ids:
        desk.set_time(db, (instant(desk.get(db, "now")) + timedelta(days=1)).isoformat())
        for oid in hub_ids:
            if ops._order(db, oid)["status"] == "IN_TRANSIT":
                event(db, oid, "RECOVERED" if oid == "UD-HUB-01" else "ARRIVED")
                event(db, oid, "ISSUED")
    return day


def exceptions(db):
    oid = "UD-CITY-01"
    for kind in ("RETURNED", "RETURN_SENT", "RETURN_RECEIVED"):
        event(db, oid, kind)
    for kind in ("WITHDRAW_REQUESTED", "WITHDRAW_SENT", "WITHDRAW_RECEIVED"):
        lot = ops._lot(db, "UD-AGED")
        ops.event(db, desk.ctx(db, {
            "lot_id": lot["id"], "event_type": kind, "pvz_id": lot["pvz_id"],
            "expected_version": lot["version"], "quantity": 1,
        }))


def read(db):
    row = db.execute("SELECT value FROM desk_meta WHERE key='unified_demo'").fetchone()
    return json.loads(row[0]) if row else None


def view(db, day):
    progress = read(db)
    if not progress:
        return None
    state = desk.state(db, "dispatcher")
    orders = [order for order in state["orders"] if order["id"].startswith("UD-")]
    counts = Counter(order["status"] for order in orders)
    stage = progress["stage"]
    economics = day["economics"] if day and day["id"] == progress.get("fleet_id") else None
    totals = state["totals"]
    actual = {key: totals[key] for key in ("rwb_cost", "rwb_contribution", "seller_profit", "pvz_profit")}
    actual["pvz_profit"] = sum(actual["pvz_profit"].values())
    plan = None
    if economics:
        plan = {key: economics[key] for key in ("all_hub", "total", "savings")}
        plan.update(orders=economics["total_units"], fleet_orders=economics["units"],
                    hub_orders=economics["total_units"] - economics["units"], relayed_orders=economics["relayed_units"])
    return {**progress, "title": "Рабочий день сети", "steps": [{"label": label} for label in LABELS],
            "next_label": LABELS[stage] if stage < len(LABELS) else None, "finished": stage == len(LABELS),
            "summary": {"orders": len(orders), "assembled": counts["ASSEMBLED"], "ready": counts["READY_FOR_PICKUP"],
                        "issued": counts["ISSUED"], "returned": counts["RESTOCKED"],
                        "hub_orders": sum(order["mode"] == "HUB" for order in orders),
                        "incidents": len(state["incidents"]),
                        "ledger_entries": len(state["ledger"]), "plan": plan, "actual": actual}}


def command(db, body, day, calculate, confirm_day, advance):
    progress = read(db)
    if body["action"] == "unified-start":
        if progress:
            raise Problem(409, "DEMO_ALREADY_STARTED", "День уже запущен. Откройте текущий этап.")
        if desk.get(db, "scenario") != "sandbox" or day or ops.snapshot(db)["lots"]:
            raise Problem(409, "DEMO_REQUIRES_SANDBOX", "Для работы начните новую свободную демосмену.")
        progress = {"id": "UD-" + uuid4().hex[:12], "version": 1, "stage": 0}
    else:
        if not progress or type(body.get("version")) is not int or body["version"] != progress["version"]:
            raise Problem(409, "DEMO_VERSION", "День изменился. Обновите текущее состояние.")
        if progress.get("fleet_id") and (not day or day["id"] != progress["fleet_id"]):
            raise Problem(409, "DEMO_PLAN_CHANGED", "План парка в этой смене заменён. Запустите рабочий день заново.")
        match progress["stage"]:
            case 0: receive(db)
            case 1: reserve(db)
            case 2: day = prepare_plan(db, progress, day, calculate, confirm_day)
            case 3: day = advance_fleet(db, day, advance, stop_at_transfer=True)
            case 4: day = deliver(db, day, advance)
            case 5: exceptions(db)
            case _: raise Problem(409, "DEMO_FINISHED", "Рабочий день уже завершён.")
        progress["stage"] += 1
        progress["version"] += 1
        desk.refresh(db)
        demand.recalculate(db)
    desk.put(db, "unified_demo", progress)
    return {"unified": view(db, day), "day": day}
