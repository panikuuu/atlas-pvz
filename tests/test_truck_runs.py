"""Test the truck API against both the local server and the packaged executable."""

import argparse
from pathlib import Path
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

from test_cases import isolated_server, request


def truck(base, body=None, key=None, role="dispatcher"):
    headers = {"X-Role":role}
    data = None
    if body is not None:
        headers.update({"Content-Type":"application/json", "Idempotency-Key":key or str(uuid4())})
        data = json.dumps(body).encode()
    with urlopen(Request(base+"/api/truck",data,headers),timeout=10) as response:
        return json.load(response)["run"]


def command(base, run, action, key=None, role="dispatcher", **data):
    return truck(base, {"action":action,"run_id":run["id"],"version":run["version"],**data}, key, role)


def confirm(base, kind, route):
    from datetime import datetime
    current = request(base,"/api/state")
    return {"action":"confirm","config":{"kind":kind,"start":route[0][0],"end":route[-1][0],"liters":24,"grams":10000,
            "departure":round(datetime.fromisoformat(current["now"]).timestamp()*1000)},
            "stops":[dict(id=point,pickup=pickup,drop=drop) for point,pickup,drop in route]}


def rejected(fn, status):
    try:
        fn()
    except HTTPError as error:
        assert error.code == status, (error.code,error.read())
    else:
        raise AssertionError(f"Expected HTTP {status}")


def verify(base):
    assert truck(base) is None
    sample = confirm(base,"sample",[("F",["Т-01","Т-02"],[]),("A",["Т-03"],["Т-01"]),
                                    ("E",[],["Т-03"]),("B",[],["Т-02"])])
    key = str(uuid4())
    run = truck(base,sample,key)
    assert truck(base,sample,key)==run
    rejected(lambda:truck(base,sample),409)
    rejected(lambda:command(base,run,"start",role="pvz"),403)
    run = command(base,run,"start")
    assert truck(base)==run
    rejected(lambda:command(base,run,"scan",kind="drop",order_id="Т-01"),422)
    rejected(lambda:command(base,run,"next"),409)
    run = command(base,run,"scan",role="pvz",kind="pickup",order_id="Т-01")
    assert command(base,run,"scan",kind="pickup",order_id="Т-01")==run
    run = command(base,run,"next",acknowledge=True)
    assert run["orders"]["Т-02"]["status"]=="MISSED" and run["load"]["ids"]==["Т-01"]
    run = command(base,run,"delay",minutes=240)
    assert any("Т-01" in value for value in run["notices"])
    run = command(base,run,"skip",acknowledge=True)
    assert run["load"]["ids"]==["Т-01"]
    assert run["orders"]["Т-03"]["status"]=="MISSED"
    assert any(v["drop"]==["Т-01"] and not v["closed"] for v in run["stops"])
    for _ in range(8):
        if run["status"]=="COMPLETED":
            break
        current=run["stops"][run["cursor"]]
        if "Т-01" in current["drop"]:
            run=command(base,run,"scan",kind="drop",order_id="Т-01")
        run=command(base,run,"next",acknowledge=True)
    assert run["status"]=="COMPLETED" and not run["load"]["ids"]
    assert run["orders"]["Т-01"]["status"]=="DELIVERED"
    print("PASS: duplicate scan, missed handoff, delay, late cargo, closed PVZ and retry stop",flush=True)

    state=request(base,"/api/state")
    assembled=[o["id"] for o in state["orders"] if o["status"]=="ASSEMBLED"]
    assert len(assembled)>=2
    o1,o2=assembled[:2]
    live=confirm(base,"shift",[("A",[o1,o2],[]),("B",[],[o1,o2])])
    too_small={**live,"config":{**live["config"],"liters":1}}
    rejected(lambda:truck(base,too_small),409)
    assert [o["id"] for o in request(base,"/api/state")["orders"] if o["status"]=="ASSEMBLED"]==assembled
    run=truck(base,live)
    assert all(request(base,"/api/orders/"+oid)["status"]=="ASSIGNED" for oid in (o1,o2))
    run=command(base,run,"cancel")
    assert all(request(base,"/api/orders/"+oid)["status"]=="ASSEMBLED" for oid in (o1,o2))
    run=truck(base,live)
    run=command(base,run,"start")
    run=command(base,run,"scan",kind="pickup",order_id=o1)
    assert request(base,"/api/orders/"+o1)["status"]=="IN_TRANSIT"
    run=command(base,run,"next",acknowledge=True)
    assert request(base,"/api/orders/"+o2)["status"]=="ASSEMBLED"
    run=command(base,run,"scan",kind="drop",order_id=o1)
    run=command(base,run,"next")
    assert run["status"]=="COMPLETED"
    assert request(base,"/api/orders/"+o1)["status"]=="READY_FOR_PICKUP"
    state=request(base,"/api/state")
    assert state["stock_errors"]==state["ledger_errors"]==0
    print("PASS: transaction, capacity, reservation, cancel, inventory, stages and ledger",flush=True)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app",type=Path,default=Path(__file__).resolve().parents[1]/"app")
    parser.add_argument("--exe",type=Path)
    args=parser.parse_args()
    with isolated_server(args.app.resolve(),args.exe) as base:
        verify(base)
