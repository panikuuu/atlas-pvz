"""Persistent truck itinerary and operations in the shift's SQLite transaction."""

from contextlib import closing
from datetime import datetime, timezone
import json
from math import isfinite
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

import desk
import operations as ops
import server
from commands import once, signature
from common import Problem
from truck_routes import STATIONS, comparison, sample_orders, travel_ms

MINUTE = 60_000
ACTIVE = {"CONFIRMED", "IN_PROGRESS"}
ORIGINAL_COMMAND = server.apply_command
ORIGINAL_QUERY = server.query


def problem(message, status=409):
    raise Problem(status, "TRUCK_OPERATION", message)


def timestamp(value):
    return round(datetime.fromisoformat(value).timestamp() * 1000)


def iso(value):
    return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS truck_run (slot INTEGER PRIMARY KEY CHECK (slot=1), data TEXT NOT NULL)")


def current(db):
    row = db.execute("SELECT data FROM truck_run WHERE slot=1").fetchone()
    return json.loads(row["data"]) if row else None


def store(db, run):
    db.execute("INSERT OR REPLACE INTO truck_run VALUES (1,?)", (json.dumps(run, ensure_ascii=False),))
    return run


def order_ids(value):
    if not isinstance(value, list) or any(not isinstance(oid, str) or not oid or len(oid)>100 for oid in value):
        problem("Ожидается список номеров заказов.", 422)
    if len(set(value)) != len(value):
        problem("Заказ указан в операции более одного раза.", 422)
    return value


def stop(point, pickup=(), drop=()):
    return {"id": point, "pickup": list(pickup), "drop": list(drop), "arrive": None,
            "leave": None, "closed": False, "actions": []}


def validate_number(value, minimum, maximum):
    if type(value) not in (int, float) or not isfinite(value) or not minimum <= value <= maximum:
        problem("Проверьте время выезда и вместимость машины.", 422)
    return value


def order_state(db, oid):
    row = db.execute("""SELECT o.*, l.volume_l, l.mass_g FROM op_orders AS o
                     JOIN op_lots AS l ON l.id=o.lot_id WHERE o.id=?""", (oid,)).fetchone()
    if row is None:
        problem(f"Заказ {oid} отсутствует в смене.")
    return row


def confirm(db, body, existing):
    if existing and existing["status"] in ACTIVE:
        problem("Завершите текущий рейс или отмените его до выезда.")
    config = body.get("config")
    raw = body.get("stops")
    if not isinstance(config, dict) or not isinstance(raw, list) or not 2 <= len(raw) <= 30:
        problem("Проверьте параметры и состав маршрута.", 422)
    kind = config.get("kind")
    if kind not in ("sample", "shift"):
        problem("Выберите источник заказов.", 422)
    now = timestamp(desk.get(db, "now"))
    depart = int(validate_number(config.get("departure"), now, now + 30*24*60*MINUTE))
    limits = {"liters": validate_number(config.get("liters"), 0.01, 100_000),
              "grams": validate_number(config.get("grams"), 1, 60_000_000)}
    visits = []
    for value in raw:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or value["id"] not in STATIONS:
            problem("Остановка отсутствует на дорожной карте.", 422)
        visits.append(stop(value["id"], order_ids(value.get("pickup")), order_ids(value.get("drop"))))
    if visits[0]["id"] != config.get("start") or visits[-1]["id"] != config.get("end"):
        problem("Старт и финиш не совпадают с маршрутным листом.", 422)
    picked = [oid for v in visits for oid in v["pickup"]]
    dropped = [oid for v in visits for oid in v["drop"]]
    if not picked or len(picked)>250 or len(set(picked))!=len(picked) or sorted(picked)!=sorted(dropped):
        problem("На каждый заказ нужна одна погрузка и одна выгрузка.", 422)
    known = sample_orders(depart) if kind == "sample" else {}
    if kind == "shift":
        for oid in picked:
            row = order_state(db, oid)
            if row["status"] != "ASSEMBLED" or row["dispatch_id"]:
                problem(f"Заказ {oid} уже закреплён или ещё не собран.")
            known[oid] = {"id": oid, "from": row["source"], "to": row["destination"],
                          "liters": row["volume_l"], "grams": row["mass_g"],
                          "due": timestamp(row["promised_at"])}
    if any(oid not in known for oid in picked):
        problem("В плане есть неизвестный тестовый заказ.", 422)
    orders = {oid: dict(known[oid], status="WAITING") for oid in picked}
    run = {"id": "T-" + uuid4().hex[:12], "status": "CONFIRMED", "version": 1,
           "kind": kind, "config": {**limits, "departure": depart, "start":visits[0]["id"], "end":visits[-1]["id"]},
           "profile": desk.get(db,"profile"),
           "stops": visits, "orders": orders, "cursor": 0, "time": depart,
           "history": [], "notices": []}
    # Validate precedence and stop assignments before reserving any order.
    onboard = set()
    for visit in visits:
        for oid in visit["drop"]:
            if oid not in onboard or orders[oid]["to"] != visit["id"]:
                problem(f"Проверьте место и порядок выгрузки {oid}.", 422)
            onboard.remove(oid)
        for oid in visit["pickup"]:
            if orders[oid]["from"] != visit["id"]:
                problem(f"Проверьте место погрузки {oid}.", 422)
            onboard.add(oid)
    retime(run)
    if run["notices"]:
        problem("Рейс не проходит проверку вместимости или срока: " + "; ".join(run["notices"][:3]))
    if kind == "shift":
        manifest = {"id": run["id"], "order_ids": picked, "mode": "SHARED_TRIP",
                    "quote_id": None, "carrier_cost": run["economics"]["operating"],
                    "created_at": desk.get(db,"now"), "window_id": "multi-stop"}
        amount, remainder = divmod(manifest["carrier_cost"], len(picked))
        for i, oid in enumerate(picked):
            ops.attach(db, oid, run["id"], "SHARED_TRIP", amount + (i<remainder), run["profile"],
                       desk.get(db, "now"), desk.REQUEST_ID.get())
        db.execute("INSERT INTO manifests VALUES (?,?)", (run["id"], desk.encode(manifest)))
    return store(db, run)


def pending(run, visit, kind):
    status = {"pickup":"WAITING", "drop":"ONBOARD"}[kind]
    return [oid for oid in visit[kind] if run["orders"][oid]["status"] == status]


def load(run, onboard):
    orders = [run["orders"][oid] for oid in onboard]
    return {"liters": round(sum(o["liters"] for o in orders), 4), "grams": sum(o["grams"] for o in orders),
            "ids": sorted(onboard)}


def fits(run, cargo):
    return cargo["liters"] <= run["config"]["liters"] + 1e-8 and cargo["grams"] <= run["config"]["grams"]


def retime(run):
    visits, orders = run["stops"], run["orders"]
    onboard = {oid for oid, o in orders.items() if o["status"] == "ONBOARD"}
    run["load"] = load(run, onboard)
    run["notices"] = []
    run["violations"] = 0
    t = run["time"]
    for i in range(run["cursor"], len(visits)):
        v = visits[i]
        if i and not v.get("actual_arrival"):
            t += travel_ms(visits[i-1]["id"], v["id"])
        t = max(t, v.get("not_before", 0), v.get("actual_arrival", 0))
        v["arrive"] = v.get("actual_arrival", t)
        pickups = [oid for oid in v["pickup"] if orders[oid]["status"]=="WAITING"]
        drops = [oid for oid in v["drop"] if orders[oid]["status"] in {"ONBOARD", "WAITING"}]
        if (drops or pickups) and not v.get("working"):
            t += 4*MINUTE
        for oid in sorted(drops, key=lambda key:orders[key]["due"]):
            if oid not in onboard:
                run["violations"] += 1
                continue
            t += MINUTE
            onboard.remove(oid)
            if t > orders[oid]["due"]:
                run["notices"].append(f"{oid} · риск опоздания")
        for oid in pickups:
            t += MINUTE
            onboard.add(oid)
        v["leave"] = t
        v["load"] = load(run, onboard)
        if not fits(run, v["load"]):
            run["violations"] += 1
            run["notices"].append(f'{STATIONS[v["id"]]["title"]} · прогноз перегруза')
    for oid in sorted(onboard):
        run["notices"].append(f"{oid} · проверьте пункт выгрузки")
    run["violations"] += len(onboard)
    billable = [o for o in orders.values() if o["status"] not in {"MISSED", "CANCELLED"}]
    service = sum(4 + len(v["pickup"])+len(v["drop"]) for v in visits if v["pickup"] or v["drop"])
    run["economics"] = comparison([v["id"] for v in visits], billable, service, run["profile"])


def reorder_remaining(run):
    def score():
        return run["violations"],len(run["notices"]),run["stops"][-1]["leave"]

    retime(run)
    best = score()
    visits=run["stops"]
    # Keep the current stop and the configured finish. Compare neighboring swaps of
    # upcoming visits against the same load, unfinished orders and earliest times.
    for _ in range(2):
        improved=False
        for i in range(run["cursor"]+1,len(visits)-2):
            if visits[i].get("not_before") or visits[i+1].get("not_before"):
                continue
            visits[i],visits[i+1]=visits[i+1],visits[i]
            retime(run)
            candidate=score()
            if candidate<best:
                improved=True
                best=candidate
            else:
                visits[i],visits[i+1]=visits[i+1],visits[i]
        if not improved:
            break
    retime(run)


def actual_time(db, run, target):
    run["time"] = max(target, run["time"], timestamp(desk.get(db,"now")) if run["kind"]=="shift" else 0)
    if run["kind"] == "shift" and run["time"] > timestamp(desk.get(db,"now")):
        desk.set_time(db, iso(run["time"]))
    return run["time"]


def release(db, run, oid, status):
    run["orders"][oid]["status"] = status
    if run["kind"] != "shift":
        return
    row = order_state(db, oid)
    if row["status"] != "ASSIGNED" or row["dispatch_id"] != run["id"]:
        problem(f"Невозможно освободить заказ {oid}. Смените состояние в маршрутном листе.")
    at = desk.get(db,"now")
    db.execute("""UPDATE op_orders SET status='ASSEMBLED', dispatch_id=NULL, mode=NULL,
               carrier_cost=0, version=version+1, last_at=? WHERE id=?""", (at, oid))
    ops._log(db, "TRUCK_RELEASED", at, row["lot_id"], oid, dispatch_id=run["id"], reason=status,
             request_id=desk.REQUEST_ID.get())
    manifest = db.execute("SELECT content FROM manifests WHERE id=?", (run["id"],)).fetchone()
    if manifest:
        value = json.loads(manifest[0])
        value["order_ids"].remove(oid)
        value["carrier_cost"] -= row["carrier_cost"]
        db.execute("UPDATE manifests SET content=? WHERE id=?", (desk.encode(value), run["id"]))


def scan(db, run, visit, body):
    kind, oid = body.get("kind"), body.get("order_id")
    if kind not in ("pickup", "drop") or not isinstance(oid,str) or oid not in visit[kind]:
        problem("Заказ не относится к выбранной операции в текущем ПВЗ.", 422)
    order = run["orders"][oid]
    previous, after = ("WAITING","ONBOARD") if kind=="pickup" else ("ONBOARD","DELIVERED")
    if any(action.get("order_id")==oid and action["kind"]==kind for action in visit["actions"]):
        return False
    if order["status"] != previous:
        problem("Заказ уже обработан или пока отсутствует в машине.")
    if kind=="pickup":
        if pending(run,visit,"drop"):
            problem("Сначала завершите выгрузку на этой остановке.")
        onboard = {key for key, item in run["orders"].items() if item["status"]=="ONBOARD"}
        if not fits(run, load(run, onboard | {oid})):
            problem("Заказ превышает свободную вместимость. Сначала завершите выгрузку.")
    visit.setdefault("actual_arrival", max(run["time"], visit["arrive"]))
    clock=timestamp(desk.get(db,"now")) if run["kind"]=="shift" else run["time"]
    at = actual_time(db, run, max(clock,run["time"],visit["actual_arrival"]) + (1 if visit.get("working") else 5)*MINUTE)
    visit["working"] = True
    if run["kind"]=="shift":
        row = order_state(db, oid)
        ops.event(db, desk.ctx(db, {"order_id":oid, "event_type":"HANDED_OVER" if kind=="pickup" else "ARRIVED",
                                   "pvz_id":visit["id"], "dispatch_id":run["id"], "expected_version":row["version"]}))
    order["status"] = after
    visit["actions"].append({"kind":kind, "order_id":oid, "at":at, "late":kind=="drop" and at>order["due"]})
    return True


def close_visit(db, run, visit, skip):
    unreceived = pending(run, visit, "pickup")
    undelivered = pending(run, visit, "drop")
    if undelivered and not skip:
        problem("В машине остались посылки для этого ПВЗ. Выгрузите их или перенесите остановку.")
    at = actual_time(db, run, max(visit["arrive"], run["time"]))
    for oid in unreceived:
        release(db, run, oid, "MISSED")
        visit["actions"].append({"kind":"missed", "order_id":oid, "at":at})
    if undelivered:
        # Keep cargo in the vehicle and retry this point after the other service stops.
        retry = stop(visit["id"], drop=undelivered)
        retry["not_before"] = at + 30*MINUTE
        next_index = run["cursor"] + 1
        final = len(run["stops"])-1
        if next_index > final:
            run["stops"].append(retry)
        else:
            run["stops"].insert(final if not(run["stops"][final]["pickup"] or run["stops"][final]["drop"]) else final+1, retry)
            if run["stops"][-1]["id"] != run["config"]["end"]:
                run["stops"].append(stop(run["config"]["end"]))
        visit["actions"].append({"kind":"retry", "at":at, "orders":undelivered})
    visit.update(closed=True, leave=at, load=load(run, {oid for oid,o in run["orders"].items() if o["status"]=="ONBOARD"}))
    run["cursor"] += 1
    if run["cursor"] == len(run["stops"]):
        run["status"] = "COMPLETED"


def advance(db, run, body):
    action = body.get("action")
    if not run or body.get("run_id") != run["id"] or body.get("version") != run["version"]:
        problem("Рейс изменился. Обновите маршрутный лист.")
    if action == "cancel" and run["status"] == "CONFIRMED":
        for oid in run["orders"]:
            release(db,run,oid,"CANCELLED")
        run["status"]="CANCELLED"
    elif action=="start" and run["status"]=="CONFIRMED":
        run["status"]="IN_PROGRESS"
        actual_time(db,run,run["time"])
    elif run["status"]=="IN_PROGRESS" and action in {"scan","delay","next","skip"}:
        visit=run["stops"][run["cursor"]]
        if action=="scan":
            if not scan(db,run,visit,body):
                return run
        elif action=="delay":
            minutes=validate_number(body.get("minutes"),1,1440)
            at=actual_time(db,run,max(run["time"],visit["arrive"])+round(minutes*MINUTE))
            visit["actual_arrival"]=visit.get("actual_arrival",at)
            visit["actions"].append({"kind":"delay","minutes":minutes,"at":at})
        else:
            if pending(run,visit,"pickup") and not body.get("acknowledge"):
                problem("Подтвердите, что непринятые посылки останутся в ПВЗ.")
            close_visit(db,run,visit,action=="skip")
    else:
        problem("Операция недоступна в текущем состоянии рейса.")
    run["history"].append({"action":action,"at":run["time"]})
    run["version"]+=1
    if action=="delay":
        reorder_remaining(run)
    else:
        retime(run)
    return store(db,run)


def guard(db, path, body, role):
    if path in {"/api/events","/api/demo/step","/api/demo/run"}:
        initialize(db)
        run=current(db)
        if run and run["kind"]=="shift" and run["status"] in ACTIVE:
            if path!="/api/events":
                problem("Сначала завершите подтверждённый рейс текущей смены.")
            order=run["orders"].get(body.get("order_id"))
            if order and order["status"] in {"WAITING","ONBOARD"} and body.get("event_type") in {"HANDED_OVER","ARRIVED","INCIDENT","RECOVERED"}:
                problem("Эта посылка закреплена за многоостановочным рейсом. Используйте маршрутный лист.")
    return ORIGINAL_COMMAND(db,path,body,role)


def order_query(db, path, args, role):
    if path.startswith("/api/orders/") and role=="dispatcher":
        oid=path.rsplit("/",1)[-1]
        linked=db.execute("SELECT dispatch_id FROM op_orders WHERE id=?", (oid,)).fetchone()
        if linked and (linked["dispatch_id"] or "").startswith("T-"):
            state=desk.state(db,role)
            order=next(item for item in state["orders"] if item["id"]==oid)
            manifest=next((item for item in state["dispatches"] if item["id"]==linked["dispatch_id"]),None)
            return {**order,"manifest":manifest,"decision":None,
                    "movements":[m for m in state["movements"] if m.get("order_id")==oid],
                    "ledger":[e for e in state["ledger"] if e["order_id"]==oid]}
    return ORIGINAL_QUERY(db,path,args,role)


class TruckHandler(server.Handler):
    def handle_request(self, post=False):
        if urlsplit(self.path).path != "/api/truck":
            return super().handle_request(post)
        self.rid=uuid4().hex
        token=desk.REQUEST_ID.set(self.rid)
        try:
            role=self.headers.get("X-Role","dispatcher")
            if role not in {"dispatcher","pvz"}:
                problem("Рейс доступен диспетчеру и сотруднику ПВЗ.",403)
            body=None
            if post:
                key=self.headers.get("Idempotency-Key","").strip()
                if not 1<=len(key)<=128:
                    problem("Требуется ключ операции.",422)
                size=int(self.headers.get("Content-Length",0))
                if not 0<size<=512_000:
                    problem("Недопустимый размер запроса.",422)
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict):
                    problem("Ожидается JSON-объект.",422)
                if role=="pvz" and body.get("action")!="scan":
                    problem("Подтверждение рейса и изменение плана доступны диспетчеру.",403)
            with server.GATE, closing(server.connect(server.DATA/"catalog.sqlite")) as registry:
                name=registry.execute("SELECT name FROM active").fetchone()["name"]
                with closing(server.connect(server.DATA/name)) as db:
                    db.execute("BEGIN IMMEDIATE" if post else "BEGIN")
                    initialize(db)
                    run=current(db)
                    if post:
                        fn=confirm if body.get("action")=="confirm" else lambda d,b,r:advance(d,r,b)
                        result=once(db,"replays",key,signature(role,"/api/truck",body),lambda:fn(db,body,run))
                    else:
                        result=run
                    db.commit()
            self.reply(200,{"run":result})
        except Problem as exc:
            self.reply(exc.status,{"error":exc.code,"message":exc.message})
        except (ValueError,TypeError,OverflowError):
            self.reply(422,{"error":"INVALID_TRUCK_INPUT","message":"Проверьте параметры операции."})
        except sqlite3.OperationalError:
            self.reply(503,{"error":"TRUCK_STORAGE","message":"Данные рейса временно недоступны."})
        finally:
            desk.REQUEST_ID.reset(token)

    def reply(self,status,data):
        self.send_data(status,json.dumps(data,ensure_ascii=False).encode("utf-8"),"application/json; charset=utf-8")


server.apply_command=guard
server.query=order_query
