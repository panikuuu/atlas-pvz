"""Verify plan economics, multi-truck custody, transfer gating and inventory."""

import argparse
from pathlib import Path
from urllib.error import HTTPError

from test_cases import isolated_server, request


def query(base):
    return request(base,"/api/fleet")


def send(base,body):
    return request(base,"/api/fleet",body)


def preview(base,scenario,**extra):
    return send(base,{"action":"plan","scenario":scenario,**extra})["plan"]


def confirm(base,plan):
    return send(base,{"action":"confirm",**plan["request"],"fingerprint":plan["fingerprint"]})["day"]


def step(base,day,v,action,**extra):
    body={"action":action,"truck":v["id"],"day_id":day["id"],"version":day["version"],**extra}
    return send(base,body)["day"]


def by_id(day,vid):
    return next(v for v in day["trucks"] if v["id"]==vid)


def rejects(action,status):
    try:
        action()
    except HTTPError as error:
        assert error.code==status,(error.code,error.read())
    else:
        raise AssertionError(f"Expected HTTP {status}")


def execute(base,day):
    for v in day["trucks"]:
        if v["status"]=="PLANNED":
            day=step(base,day,v,"start")
    for _ in range(160):
        if day["status"]=="DONE":
            return day
        route=None
        for truck in day["trucks"]:
            if truck["status"]=="DONE":
                continue
            stop=truck["stops"][truck["cursor"]]
            event=next((e for e in stop["events"] if not e["done"]),None)
            if event and event["kind"]=="relay_pickup" and day["custody"][event["batch"]]["kind"]!="relay":
                continue
            timestamp=event["at"] if event else stop["leave"]
            if route is None or timestamp<route[0]:
                route=(timestamp,truck,event)
        assert route is not None, "All unfinished trucks are waiting on each other"
        _,truck,event=route
        if event:
            day=step(base,day,truck,"scan",batch=event["batch"],operation=event["kind"])
        else:
            day=step(base,day,truck,"next")
    raise AssertionError("Fleet shift did not finish")


def verify(base):
    assert query(base)["day"] is None
    p=preview(base,"weekday")
    economics=p["economics"]
    assert (economics["units"],economics["relayed_units"],economics["savings"])==(70,14,380933)
    assert p["without_relay"]>economics["total"]
    assert sum(economics["costs"].values())+economics["coordination"]+economics["remaining_hub"]==economics["total"]
    surge=preview(base,"peak")["economics"]
    assert (surge["total_units"],surge["units"],surge["relayed_units"])==(144,137,28)
    quiet=preview(base,"quiet")["economics"]
    assert quiet["units"]==quiet["savings"]==0 and quiet["active_trial_delta"]<0
    stressed=preview(base,"weekday",prices={"hub_city":0,"hub_rural":0})["economics"]
    assert stressed["units"]==stressed["savings"]==0
    rejects(lambda:send(base,{"action":"confirm",**p["request"],"fingerprint":"stale"}),409)
    day=confirm(base,p)
    rejects(lambda:confirm(base,p),409)
    relay_truck=by_id(day,"М2")
    day=step(base,day,relay_truck,"start")
    event=next(e for e in relay_truck["stops"][0]["events"] if e["kind"]=="relay_pickup")
    rejects(lambda:step(base,day,relay_truck,"scan",batch=event["batch"],operation="relay_pickup"),409)
    assert day==query(base)["day"]
    day=execute(base,day)
    assert all(row["kind"]=="delivered" for row in day["custody"].values())
    relay=[e for e in day["journal"] if e["batch"]=="П-04"]
    assert [e["kind"] for e in relay]==["pickup","relay_drop","relay_pickup","drop"]
    assert relay[1]["point"]==relay[2]["point"] and relay[1]["truck"]!=relay[2]["truck"]
    assert relay[2]["at"]>=relay[1]["at"]+12
    print("PASS sample: cost reconciliation, peak, quiet, two trucks and explicit relay custody",flush=True)
    assembled=[o["id"] for o in request(base,"/api/state")["orders"] if o["status"]=="ASSEMBLED"]
    vehicles=[{"id":vid,"start":"A","end":"B","start_min":550+i*110,"end_min":690+i*110,
               "liters":12,"kg":8,"planned":True} for i,vid in enumerate(("live1","live2"))]
    live=preview(base,"live",trucks=vehicles,prices={"coordination_day":0})
    count=live["economics"]["units"]
    assert count and count<=len(assembled)
    day=confirm(base,live)
    ids=[o["id"] for bid in day["custody"] for o in day["batches"][bid]["orders"]]
    assert all(request(base,"/api/orders/"+oid)["status"]=="ASSIGNED" for oid in ids)
    day=execute(base,day)
    assert all(request(base,"/api/orders/"+oid)["status"]=="READY_FOR_PICKUP" for oid in ids)
    state=request(base,"/api/state")
    assert state["stock_errors"]==state["ledger_errors"]==0
    print("PASS live: reserve, physical delivery and ledger reconciliation",flush=True)


def verify_live_relay(base):
    vehicles=[
        {"id":"А","start":"A","end":"C","start_min":540,"end_min":625,"liters":40,"kg":30,"planned":True},
        {"id":"Б","start":"C","end":"B","start_min":620,"end_min":710,"liters":40,"kg":30,"planned":True},
    ]
    p=preview(base,"live",trucks=vehicles,prices={"hub_city":110,"coordination_day":0})
    assert p["economics"]["relayed_units"]>0
    day=execute(base,confirm(base,p))
    oid=next(o["id"] for bid in day["custody"] for o in day["batches"][bid]["orders"])
    details=request(base,"/api/orders/"+oid)
    assert details["status"]=="READY_FOR_PICKUP"
    assert any(m["to"]=="RELAY:C" for m in details["movements"])
    assert sum(e["service"]=="SELLER_LOGISTICS" for e in details["ledger"])==1
    state=request(base,"/api/state")
    assert state["stock_errors"]==state["ledger_errors"]==0
    print("PASS live relay: buffer movement, final delivery and single seller logistics charge",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app",type=Path,default=Path(__file__).resolve().parents[1]/"app")
    parser.add_argument("--exe",type=Path)
    args=parser.parse_args()
    with isolated_server(args.app.resolve(),args.exe) as base:
        verify(base)
    with isolated_server(args.app.resolve(),args.exe) as base:
        verify_live_relay(base)
