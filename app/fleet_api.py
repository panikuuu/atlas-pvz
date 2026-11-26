"""Fleet planning and ordered custody changes within the Atlas shift database."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from itertools import batched
import json
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

import desk
import fleet
import operations as ops
import server
from commands import once, signature
from common import Problem
from truck_runs import TruckHandler, current, initialize as init_truck, order_state, problem

MSK = timezone(timedelta(hours=3))
PREVIOUS_COMMAND = server.apply_command


def init(db):
    db.execute("CREATE TABLE IF NOT EXISTS fleet_day (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL)")


def load_day(db):
    row=db.execute("SELECT data FROM fleet_day WHERE id=1").fetchone()
    return json.loads(row[0]) if row else None


def save(db,day):
    db.execute("INSERT OR REPLACE INTO fleet_day VALUES(1,?)",(json.dumps(day,ensure_ascii=False),))
    return day


def clock(db):
    return datetime.fromisoformat(desk.get(db,"now")).astimezone(MSK)


def minute(date):
    return date.hour*60+date.minute+date.second/60


def live_batches(db, vehicles):
    now=clock(db)
    ready=minute(now)
    if any(vehicle["start_min"]<ready-1 for vehicle in vehicles):
        problem("Для текущей смены задайте время старта машин с учётом часов смены.",422)
    eligible=[]
    for o in ops.snapshot(db)["orders"]:
        if o["status"]!="ASSEMBLED" or o["dispatch_id"]:
            continue
        due=datetime.fromisoformat(o.get("selected_promised_at") or o["promised_at"]).astimezone(MSK)
        eligible.append({**o,"deadline":(due.date()-now.date()).days*1440+minute(due)})
    if not eligible:
        problem("В смене нет свободных собранных заказов.",422)
    if len(eligible)>60:
        problem("Для текущей версии расчёт ограничен 60 собранными заказами на смену.",422)
    groups={}
    for o in sorted(eligible,key=lambda o:(o["deadline"],o["id"])):
        groups.setdefault((o["source"],o["destination"]),[]).append(o)
    batches={}
    for (source,destination),orders in groups.items():
        for group in batched(orders,5):
            bid=f"С-{len(batches)+1:02}"
            batches[bid]={"id":bid,"from":source,"to":destination,"qty":len(group),
                "liters":sum(o["volume_l"] for o in group),"kg":sum(o["mass_g"] for o in group)/1000,
                "ready":ready,"due":min(o["deadline"] for o in group),
                "orders":[{"id":o["id"],"version":o["version"]} for o in group]}
    return batches


def calculate(db,body):
    scenario=body.get("scenario","weekday")
    live=scenario=="live"
    fixture=fleet.FIXTURE["scenarios"].get(scenario) if isinstance(scenario,str) else None
    if not (fixture or live):
        problem("Выберите сценарий.",422)
    vehicles=fleet.validate_vehicles(body.get("trucks",fixture["trucks"] if fixture else None))
    prices=fleet.prices_for(body.get("prices",{}))
    batches=live_batches(db,vehicles) if live else fleet.demo_batches(fixture)
    allow=body.get("allow_transfer",True)
    if type(allow) is not bool:
        problem("Проверьте настройку передач.",422)
    plan=fleet.plan(vehicles,batches,prices,allow)
    plan["scenario"]=scenario
    plan["date"]=clock(db).date().isoformat()
    plan["request"]={"scenario":scenario,"trucks":vehicles,"prices":prices,"allow_transfer":allow}
    plan["fingerprint"]=sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return plan


def operational(day):
    return bool(day and day["status"]=="ACTIVE" and day["scenario"]=="live")


def confirm_day(db, body, day):
    if day and day["status"]=="ACTIVE":
        problem("Завершите активный план парка перед подтверждением нового.")
    plan=calculate(db,body)
    if plan["fingerprint"]!=body.get("fingerprint"):
        problem("Заказы, смена или ставки изменились. Сначала пересчитайте план.")
    trips=[v for v in plan["trucks"] if v["used"]]
    if not trips:
        problem("По этим условиям заказы остаются на хабовом маршруте.",422)
    plan["trucks"]=trips
    init_truck(db)
    active=current(db)
    if plan["scenario"]=="live" and active and active["kind"]=="shift" and active["status"] in {"CONFIRMED","IN_PROGRESS"}:
        problem("Завершите текущий рейс до подтверждения живого плана парка.")
    plan.update(id="T-"+uuid4().hex[:12],version=1,status="ACTIVE",custody={},journal=[])
    for v in trips:
        v.update(status="PLANNED",cursor=0,time=v["start_min"])
        for visit in v["stops"]:
            for event in visit["events"]:
                if event["kind"]=="pickup":
                    plan["custody"][event["batch"]]={"kind":"origin","owner":visit["point"]}
                event["done"]=False
    if plan["scenario"]=="live":
        ids=sorted(o["id"] for bid in plan["custody"] for o in plan["batches"][bid]["orders"])
        cost=sum(v["costs"][key] for v in trips for key in ("fuel","wear","driver","dispatch"))
        unit,remainder=divmod(cost,len(ids))
        for i,oid in enumerate(ids):
            ops.attach(db,oid,plan["id"],"SHARED_TRIP",unit+(i<remainder),desk.get(db,"profile"),
                       desk.get(db,"now"),desk.REQUEST_ID.get())
        manifest={"id":plan["id"],"order_ids":ids,"mode":"SHARED_TRIP","quote_id":None,"carrier_cost":cost,
                  "created_at":desk.get(db,"now"),"window_id":"fleet"}
        db.execute("INSERT INTO manifests VALUES(?,?)",(plan["id"],desk.encode(manifest)))
    return save(db,plan)


def update_clock(db, day, v, when):
    if day["scenario"]=="live":
        date=datetime.fromisoformat(day["date"]).replace(tzinfo=MSK)
        target=date+timedelta(minutes=when)
        now=clock(db)
        if target>now:
            desk.set_time(db,target.isoformat())
        when=(max(now,target)-date).total_seconds()/60
    v["time"]=max(v["time"],round(when,4))
    return v["time"]


def apply_stock(db,day,oid,point,kind):
    row=order_state(db,oid)
    if kind in ("pickup","drop"):
        event="HANDED_OVER" if kind=="pickup" else "ARRIVED"
        ops.event(db,desk.ctx(db,{"order_id":oid,"event_type":event,"pvz_id":point,
                                "dispatch_id":day["id"],"expected_version":row["version"]}))
        return
    ctx=desk.get(db,"now")
    eid=ops._log(db,"FLEET_RELAY_IN" if kind=="relay_drop" else "FLEET_RELAY_OUT",ctx,
                 row["lot_id"],oid,dispatch_id=day["id"],request_id=desk.REQUEST_ID.get())
    place="RELAY:"+point if kind=="relay_drop" else "IN_TRANSIT"
    ops._move(db,eid,ops._unit(db,row["unit_id"]),place,ctx)
    db.execute("UPDATE op_orders SET last_at=?,version=version+1 WHERE id=?",(ctx,oid))


def find_event(stop,body):
    return next((item for item in stop["events"] if item["batch"]==body.get("batch")
                 and item["kind"]==body.get("operation")),None)


def scan(db,day,v,stop,body):
    event=find_event(stop,body)
    if event is None:
        problem("Партия отсутствует на текущей остановке.",422)
    if event["done"]:
        return False
    oid,kind=event["batch"],event["kind"]
    batch=day["batches"][oid]
    point=stop["point"]
    custody=day["custody"]
    prior=custody[oid]
    expected={"pickup":("origin",point),"drop":("truck",v["id"]),
              "relay_drop":("truck",v["id"]),"relay_pickup":("relay",point)}[kind]
    if (prior["kind"],prior["owner"])!=expected:
        problem("Проверьте предыдущую передачу. Партия пока находится в другом месте.")
    if kind in {"pickup","relay_pickup"}:
        if any(not e["done"] and e["kind"] in {"drop","relay_drop"} for e in stop["events"]):
            problem("Сначала завершите выгрузку на этой точке.")
        cargo=[day["batches"][key] for key,row in custody.items() if row["kind"]=="truck" and row["owner"]==v["id"]]
        if sum(o["liters"] for o in cargo)+batch["liters"]>v["liters"] or sum(o["kg"] for o in cargo)+batch["kg"]>v["kg"]+1e-8:
            problem("Груз превышает доступную вместимость машины.")
    if kind=="relay_drop":
        staged=sum(day["batches"][key]["liters"] for key,row in custody.items() if row["kind"]=="relay" and row["owner"]==point)
        free=fleet.RELAYS[point]
        if day["scenario"]=="live":
            free=min(free,desk.free_space(ops.snapshot(db),point))
        if staged+batch["liters"]>free:
            problem("В буфере передачи ПВЗ не хватает места.")
    earliest=prior.get("at",0)+fleet.TRANSFER_BUFFER if kind=="relay_pickup" else 0
    actual=update_clock(db,day,v,max(event["at"],v["time"]+fleet.work_minutes(batch["qty"]),earliest))
    if day["scenario"]=="live":
        for actual_order in batch["orders"]:
            apply_stock(db,day,actual_order["id"],point,kind)
    destination={"pickup":("truck",v["id"]),"drop":("delivered",point),
                 "relay_drop":("relay",point),"relay_pickup":("truck",v["id"])}[kind]
    custody[oid]=dict(kind=destination[0],owner=destination[1],at=actual)
    event.update(done=True,actual=actual,late=(kind=="drop" and actual>batch["due"]))
    day["journal"].append({"truck":v["id"],"point":point,"batch":oid,"kind":kind,"at":actual})
    return True


def advance(db,day,body):
    if not day or day["status"]!="ACTIVE" or day["id"]!=body.get("day_id") or day["version"]!=body.get("version"):
        problem("План изменился. Откройте актуальное состояние парка.")
    action=body.get("action")
    v=next((v for v in day["trucks"] if v["id"]==body.get("truck")),None)
    if v is None:
        problem("Выберите машину.",422)
    if action=="start" and v["status"]=="PLANNED":
        v["status"]="RUNNING"
    elif action in {"scan","next"} and v["status"]=="RUNNING":
        stop=v["stops"][v["cursor"]]
        if action=="scan":
            if not scan(db,day,v,stop,body):
                return day
        else:
            if any(not e["done"] for e in stop["events"]):
                problem("На остановке есть ещё операции. Проверьте погрузку и выгрузку.")
            update_clock(db,day,v,max(v["time"],stop["leave"]))
            v["cursor"]+=1
            if v["cursor"]==len(v["stops"]):
                v["status"]="DONE"
            else:
                next_point=v["stops"][v["cursor"]]["point"]
                v["time"]+=fleet.minutes(stop["point"],next_point)
    else:
        problem("Действие недоступно на текущем этапе.")
    if all(v["status"]=="DONE" for v in day["trucks"]):
        if any(row["kind"]!="delivered" for row in day["custody"].values()):
            problem("В парке остался недоставленный груз.")
        day["status"]="DONE"
    day["version"]+=1
    return save(db,day)


def protected(db,path,body,role):
    if path in {"/api/events","/api/demo/run","/api/demo/step","/api/truck"}:
        init(db)
        day=load_day(db)
        if operational(day):
            if path in {"/api/demo/run","/api/demo/step"}:
                problem("Сначала завершите живой план парка.")
            for bid,location in day["custody"].items():
                if location["kind"]!="delivered" and any(o["id"]==body.get("order_id") for o in day["batches"][bid]["orders"]):
                    problem("Заказ закреплён за парком. Используйте экран «Парк машин».")
    return PREVIOUS_COMMAND(db,path,body,role)


class FleetHandler(TruckHandler):
    def handle_request(self,post=False):
        if urlsplit(self.path).path!="/api/fleet":
            return super().handle_request(post)
        self.rid=uuid4().hex
        token=desk.REQUEST_ID.set(self.rid)
        try:
            role=self.headers.get("X-Role","dispatcher")
            if role not in {"dispatcher","pvz"}:
                problem("Парк доступен диспетчеру и сотруднику ПВЗ.",403)
            body={}
            if post:
                length=int(self.headers.get("Content-Length",0))
                if not 1<=length<=100_000:
                    problem("Проверьте размер запроса.",422)
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):
                    problem("Ожидается объект JSON.",422)
                if role=="pvz" and body.get("action")!="scan":
                    problem("Изменение плана доступно диспетчеру.",403)
            with server.GATE, closing(server.connect(server.DATA/"catalog.sqlite")) as reg:
                name=reg.execute("SELECT name FROM active").fetchone()["name"]
                with closing(server.connect(server.DATA/name)) as db:
                    db.execute("BEGIN IMMEDIATE" if post else "BEGIN")
                    init(db)
                    day=load_day(db)
                    action=body.get("action")
                    if not post:
                        result={"day":day,"settings":fleet.FIXTURE}
                    elif action=="plan":
                        result={"plan":calculate(db,body)}
                    else:
                        key=self.headers.get("Idempotency-Key","").strip()
                        if not 1<=len(key)<=128:
                            problem("Укажите ключ операции.",422)
                        engine=confirm_day if action=="confirm" else lambda a,b,c:advance(a,c,b)
                        day=once(db,"replays",key,signature(role,"/api/fleet",body),lambda:engine(db,body,day))
                        result={"day":day}
                    db.commit()
            self.reply(200,result)
        except Problem as exc:
            self.reply(exc.status,{"error":exc.code,"message":exc.message})
        except (ValueError,TypeError,OverflowError) as exc:
            self.reply(422,{"error":"INVALID_FLEET","message":str(exc)})
        except sqlite3.OperationalError:
            self.reply(503,{"error":"FLEET_STORAGE","message":"Данные парка временно недоступны."})
        finally:
            desk.REQUEST_ID.reset(token)


server.apply_command=protected
