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


def verify_assortments(base):
    settings=query(base)["settings"]
    results={}
    for scenario in ("assortment","bulky","deadlines"):
        plan=preview(base,scenario)
        e, f=plan["economics"],plan["financials"]
        results[scenario]=plan
        orders=f["orders"]
        assert len({o["id"] for o in orders})==len(orders)==e["total_units"]
        assert len({o["sku"] for o in orders})>=3
        assert sum(o["channel"]=="fleet" for o in orders)==e["units"]
        assert sum(o["physical_cost"] for o in orders)==f["rwb_cost"]==e["total"]-e["costs"]["rebate"]
        assert f["rwb_revenue"]-f["rwb_cost"]==f["rwb_profit"]
        assert sum(o["profit"] for o in f["by_seller"])==f["seller_profit"]
        visits={}
        for truck in plan["trucks"]:
            for stop in truck["stops"]:
                assert stop.get("liters_after",0)<=truck["liters"]
                assert stop.get("kg_after",0)<=truck["kg"]
                if stop["events"]:
                    assert stop["bay"]==1
                    visits.setdefault(stop["point"],[]).append((stop["service_from"],stop["leave"]))
        for timeline in visits.values():
            ordered=sorted(timeline)
            assert all(a[1]<=b[0]+1e-8 for a,b in zip(ordered,ordered[1:]))
        for o in orders:
            if o["channel"]=="fleet":
                assert o["route"][0]["point"]==o["from"] and o["route"][-1]["point"]==o["to"]
                assert o["route"][-1]["at"]<=o["due"]
                assert [leg["operation"] for leg in o["route"]] in (
                    ["pickup","drop"],["pickup","relay_drop","relay_pickup","drop"])
        for row in f["seller_rates"]:
            if row["recommended"] is not None:
                assert row["minimum"]<=row["recommended"]<=row["maximum"]
                assert row["rwb_profit"]>=row["orders"]*f["targets"]["rwb_per_order"]
                assert row["seller_profit"]>=row["orders"]*f["targets"]["seller_per_order"]
    first=results["assortment"]
    assert first["economics"]["relayed_units"]>0
    assert len({p["economics"]["units"] for p in results.values()})==3
    reduced=preview(base,"assortment",trucks=[{**v,"liters":2} for v in settings["scenarios"]["assortment"]["trucks"]])
    assert reduced["economics"]["units"]<first["economics"]["units"]
    assert reduced["financials"]["rwb_profit"]!=first["financials"]["rwb_profit"]
    assert reduced["financials"]["pvz_profit"]!=first["financials"]["pvz_profit"]
    assert reduced["financials"]["seller_profit"]!=first["financials"]["seller_profit"]
    assert {o["id"] for o in reduced["financials"]["orders"]}=={o["id"] for o in first["financials"]["orders"]}
    original=preview(base,"assortment",contract="original",targets={"seller_per_order":100000})
    assert original["prices"]["rebate"]==10
    assert any(r["recommended"] is None for r in original["financials"]["seller_rates"])
    rejects(lambda:preview(base,"assortment",targets={"seller_per_order":0}),422)
    print("PASS assortments: order traceability, shared berth, capacity, margins and contract thresholds",flush=True)


def verify(base):
    assert query(base)["day"] is None
    verify_assortments(base)
    network=preview(base,"network")["economics"]
    rows=network["by_pvz"]
    assert len(rows)==9 and all(row["work_minutes"]>0 for row in rows)
    assert network["units"]==116 and network["relayed_units"]==14
    assert sum(row["baseline"] for row in rows)==network["all_hub"]==1042000
    assert sum(row["actual"] for row in rows)==network["total"]==491003
    assert sum(row["rwb_effect"] for row in rows)==network["savings"]==550997
    assert sum(row["pvz_revenue"] for row in rows)==network["costs"]["pvz"]+network["costs"]["transfer_handling"]
    assert sum(row["pvz_margin"] for row in rows)==8450
    assert sum(row["seller_rebate"] for row in rows)==network["costs"]["rebate"]
    assert sum(row["pickup"] for row in rows)==sum(row["drop"] for row in rows)==116
    assert sum(row["relay_drop"] for row in rows)==sum(row["relay_pickup"] for row in rows)==14
    print("PASS nine PVZ: active stops and exact reconciliation of park, partners and seller rebates",flush=True)
    p=preview(base,"weekday")
    economics=p["economics"]
    assert (economics["units"],economics["relayed_units"],economics["savings"])==(70,14,380933)
    assert p["without_relay"]>economics["total"]
    assert sum(economics["costs"].values())+economics["coordination"]+economics["remaining_hub"]==economics["total"]
    surge=preview(base,"peak")["economics"]
    assert (surge["total_units"],surge["units"],surge["relayed_units"])==(144,137,28)
    quiet=preview(base,"quiet")["economics"]
    assert quiet["units"]==quiet["savings"]==0 and quiet["active_trial_delta"]<0
    assert len(quiet["by_pvz"])==9 and all(row["pvz_margin"]==0 for row in quiet["by_pvz"])
    stressed=preview(base,"weekday",prices={"hub_city":0,"hub_rural":0})["economics"]
    assert stressed["units"]==stressed["savings"]==0
    rejects(lambda:send(base,{"action":"confirm",**p["request"],"fingerprint":"stale"}),409)
    day=confirm(base,p)
    pvz=request(base,"/api/fleet",role="pvz")
    assert "financials" not in pvz["day"]
    assert "cost" not in pvz["day"]["batches"]["П-01"]["orders"][0]
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
    assert query(base)["day"]["live_results"]["orders"]==0
    day=execute(base,day)
    assert all(request(base,"/api/orders/"+oid)["status"]=="READY_FOR_PICKUP" for oid in ids)
    actual=query(base)["day"]["live_results"]
    assert actual["orders"]==len(ids) and actual["rwb_cost"]>0
    order=request(base,"/api/orders/"+ids[0])
    request(base,"/api/events",{"order_id":order["id"],"pvz_id":order["destination"],
                               "event_type":"ISSUED","quantity":1,"expected_version":order["version"]})
    issued=query(base)["day"]["live_results"]
    assert issued["seller_profit"]>actual["seller_profit"]
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
