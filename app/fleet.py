"""Costed pickup and delivery across a small fleet and scheduled relay points."""

from collections import Counter
from itertools import pairwise
import json
from math import isfinite
from pathlib import Path

from truck_routes import STATIONS, distance, travel_ms

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "fleet.json").read_text(encoding="utf-8"))
RELAYS = FIXTURE["relays"]
TRANSFER_BUFFER = 12
ROUND_TRIP_SPEED_MIN = 60_000


def minutes(a, b):
    return travel_ms(a, b) / ROUND_TRIP_SPEED_MIN


def cost_parts(km, duration, handling, prices, dedicated=False):
    return {
        "fuel": round(km * prices["consumption"] / 100 * prices["diesel"] * 100),
        "wear": round(km * prices["wear"] * 100),
        "driver": round(duration / 60 * prices["driver_hour"] * 100),
        "pvz": round(handling / 60 * prices["pvz_hour"] * 100),
        "dispatch": round(prices["dedicated_fixed"] * 100) if dedicated else 0,
    }


def is_rural(point):
    return STATIONS[point]["area"] in {"Село","Деревня","Посёлок"}


def estimate_hub(batch, prices):
    key="hub_rural" if is_rural(batch["from"]) or is_rural(batch["to"]) else "hub_city"
    return round(prices[key]*100)*batch["qty"]


def prices_for(changes):
    prices=dict(FIXTURE["prices"])
    if not isinstance(changes,dict) or any(key not in prices for key in changes):
        raise ValueError("Неизвестный параметр экономики.")
    for key,value in changes.items():
        if type(value) not in (int,float) or not isfinite(value) or not 0<=value<=10000:
            raise ValueError("Все ставки должны быть числами от 0 до 10 000.")
        prices[key]=value
    return prices


def demo_batches(scenario):
    result={}
    for i,(source,dest,count,ready,due) in enumerate(scenario["batches"],1):
        oid=f"П-{i:02}"
        result[oid]={"id":oid,"from":source,"to":dest,"qty":count,"liters":count*2.0,
                     "kg":count*.6,"ready":ready,"due":due}
    return result


def validate_vehicles(vehicles):
    if not isinstance(vehicles,list) or not 1<=len(vehicles)<=6:
        raise ValueError("Добавьте от одной до шести машин.")
    clean=[]
    for row in vehicles:
        if not isinstance(row,dict) or not isinstance(row.get("id"),str) or not 1<=len(row["id"])<=20:
            raise ValueError("Укажите короткое название машины.")
        for field in ("start","end"):
            if not isinstance(row.get(field),str) or row[field] not in STATIONS:
                raise ValueError("Проверьте точки старта и финиша.")
        for field,lower,upper in (("liters",.01,100000),("kg",.01,60000),("start_min",0,1439),("end_min",1,1440)):
            value=row.get(field)
            if type(value) not in (int,float) or not isfinite(value) or not lower<=value<=upper:
                raise ValueError("Проверьте время и вместимость машины.")
        if row["start_min"]>=row["end_min"] or type(row.get("planned")) is not bool:
            raise ValueError("Финиш машины должен быть позже старта.")
        clean.append({key:row[key] for key in ("id","start","end","liters","kg","start_min","end_min","planned")})
    if len(set(v["id"] for v in clean))!=len(clean):
        raise ValueError("У каждой машины должно быть своё название.")
    return sorted(clean,key=lambda v:(v["start_min"],v["id"]))


def action(oid, point, kind):
    return {"batch":oid,"point":point,"kind":kind}


def positions(route, event, min_index):
    point=event["point"]
    visits=sum(row[0]==point for row in route)
    for i in range(min_index,len(route)):
        if route[i][0]==point:
            yield route[:i]+[(point,route[i][1]+[event])]+route[i+1:],i
        if i and visits<2 and route[i][0]!=point and route[i-1][0]!=point:
            yield route[:i]+[(point,[event])]+route[i:],i


def inserted(route, first, second):
    for partial,i in positions(route,first,0):
        for complete,_ in positions(partial,second,i+1):
            yield complete


def work_minutes(qty):
    return 0.25*qty


def drive(route, vehicle, batches, arrivals, prices):
    stops=[]
    onboard=set()
    t=vehicle["start_min"]
    km=handling=0.0
    received={}
    previous=vehicle["start"]
    for point,events in route:
        t+=minutes(previous,point)
        km+=distance(previous,point)
        previous=point
        if not events:
            stops.append({"point":point,"arrive":t,"leave":t,"events":[]})
            continue
        opening,closing=FIXTURE["windows"][point]
        t=max(t,opening)
        arrival=t
        t+=4
        handling+=4
        details=[]
        for event in sorted(events,key=lambda e:e["kind"] in {"pickup","relay_pickup"}):
            oid=event["batch"]
            batch=batches[oid]
            kind=event["kind"]
            duration=work_minutes(batch["qty"])
            if kind in {"pickup","relay_pickup"}:
                ready=batch["ready"] if kind=="pickup" else arrivals.get(oid,float("inf"))+TRANSFER_BUFFER
                t=max(t,ready)+duration
                onboard.add(oid)
                if (sum(batches[key]["liters"] for key in onboard)>vehicle["liters"] or
                    sum(batches[key]["kg"] for key in onboard)>vehicle["kg"]+1e-8):
                    return None
            else:
                if oid not in onboard:
                    return None
                t+=duration
                onboard.remove(oid)
                if kind=="relay_drop":
                    received[oid]=t
                elif t>batch["due"]:
                    return None
            details.append({**event,"at":t,"qty":batch["qty"]})
            handling+=duration
        if t>closing or t>vehicle["end_min"]:
            return None
        stops.append({"point":point,"arrive":arrival,"leave":t,"events":details,
                      "liters_after":round(sum(batches[key]["liters"] for key in onboard),2),
                      "kg_after":round(sum(batches[key]["kg"] for key in onboard),3)})
    if onboard or t>vehicle["end_min"]:
        return None
    baseline=distance(vehicle["start"],vehicle["end"]) if vehicle["planned"] else 0
    baseline_min=minutes(vehicle["start"],vehicle["end"]) if vehicle["planned"] else 0
    has_work=any(stop["events"] for stop in stops)
    if not has_work:
        return {"used":False,"received":{},"stops":stops,"km":km,"extra_km":0,
                "costs":cost_parts(0,0,0,prices),"finish":t}
    extra=max(0,km-baseline)
    costs=cost_parts(extra,max(0,t-vehicle["start_min"]-baseline_min),handling,prices,not vehicle["planned"])
    return {"used":True,"received":received,"stops":stops,"km":km,"extra_km":extra,
            "costs":costs,"finish":t}


def schedule(routes, vehicles, batches, prices):
    arrivals={}
    output=[]
    transfer_events={}
    for route,vehicle in zip(routes,vehicles):
        trip=drive(route,vehicle,batches,arrivals,prices)
        if trip is None:
            return None
        arrivals.update(trip.pop("received"))
        for visit in trip["stops"]:
            for event in visit["events"]:
                if event["kind"] in {"relay_pickup","relay_drop"}:
                    transfer_events.setdefault(visit["point"],[]).append(event)
        output.append({**vehicle,**trip})
    for point,events in transfer_events.items():
        liters=0
        for event in sorted(events,key=lambda e:(e["at"],e["kind"]!="relay_pickup")):
            volume=batches[event["batch"]]["liters"]
            liters+=volume if event["kind"]=="relay_drop" else -volume
            if liters>RELAYS[point] or liters < -1e-8:
                return None
    return output


def summarize(trips, batches, prices):
    costs=Counter()
    served,transfer=set(),set()
    for trip in trips:
        costs.update(trip["costs"])
        for v in trip["stops"]:
            for e in v["events"]:
                if e["kind"]=="drop":
                    served.add(e["batch"])
                if e["kind"]=="relay_drop":
                    transfer.add(e["batch"])
    units=sum(batches[oid]["qty"] for oid in served)
    relay_units=sum(batches[oid]["qty"] for oid in transfer)
    for field in ("packing","rebate","expected_extra_risk"):
        costs[field]=round(prices[field]*100)*units
    costs["transfer_handling"]=round(prices["transfer_handling"]*100)*relay_units
    route_cost=sum(costs.values())
    hub_base=sum(estimate_hub(b,prices) for b in batches.values())
    hub_residual=sum(estimate_hub(b,prices) for oid,b in batches.items() if oid not in served)
    total=route_cost+hub_residual
    return {"costs":dict(costs),"all_hub":hub_base,"remaining_hub":hub_residual,"direct_cost":route_cost,
            "total":total,"savings":hub_base-total,"units":units,"relayed_units":relay_units,
            "total_units":sum(b["qty"] for b in batches.values()),
            "hub_remaining":[b for oid,b in batches.items() if oid not in served],
            "break_even_per_unit":route_cost/units if units else None}


def solve(vehicles,batches,prices,allow_transfer=True,volume_first=False):
    def priority(order):
        due,value=order["due"],-estimate_hub(order,prices)
        return (value,due,order["id"]) if volume_first else (due,value,order["id"])
    orders=sorted(batches.values(),key=priority)
    routes=[[(v["start"],[]),(v["end"],[])] for v in vehicles]
    # Ignore vehicles whose basic path cannot fit even without a pickup.
    pairs=[(v,r) for v,r in zip(vehicles,routes) if v["start_min"]+minutes(v["start"],v["end"])<=v["end_min"]]
    vehicles=[v for v,_ in pairs]
    routes=[r for _,r in pairs]
    trips=schedule(routes,vehicles,batches,prices)
    best_cost=summarize(trips,batches,prices)["total"]
    for o in orders:
        oid,source,dest=o["id"],o["from"],o["to"]
        best=None
        for i,route in enumerate(routes):
            for updated in inserted(route,action(oid,source,"pickup"),action(oid,dest,"drop")):
                candidate=routes[:i]+[updated]+routes[i+1:]
                result=schedule(candidate,vehicles,batches,prices)
                if result is not None:
                    cost=summarize(result,batches,prices)["total"]
                    if cost<best_cost:
                        best_cost,best=cost,(candidate,result)
        if allow_transfer:
            for mid in sorted(RELAYS.keys()-{source,dest}):
                for i,first in enumerate(routes):
                    for j in range(i+1,len(routes)):
                        for left in inserted(first,action(oid,source,"pickup"),action(oid,mid,"relay_drop")):
                            # Prefilter locally impossible inbound paths before the Cartesian insertion.
                            if not any(x["kind"]=="relay_pickup" for _,events in left for x in events):
                                if drive(left,vehicles[i],batches,{},prices) is None:
                                    continue
                            for right in inserted(routes[j],action(oid,mid,"relay_pickup"),action(oid,dest,"drop")):
                                candidate=routes.copy()
                                candidate[i],candidate[j]=left,right
                                result=schedule(candidate,vehicles,batches,prices)
                                if result is not None:
                                    cost=summarize(result,batches,prices)["total"]
                                    if cost<best_cost:
                                        best_cost,best=cost,(candidate,result)
        if best:
            routes,trips=best
    return {"trucks":trips,"economics":summarize(trips,batches,prices)}


def split_cost(amount, weights):
    """Split integer kopecks by weight and keep the exact original sum."""
    if not weights:
        return {}
    total=sum(weights.values())
    amounts={}
    remainders=[]
    for key,weight in weights.items():
        amounts[key],remainder=divmod(amount*weight,total)
        remainders.append((remainder,key))
    residual=amount-sum(amounts.values())
    for _,key in sorted(remainders,key=lambda x:(-x[0],x[1]))[:residual]:
        amounts[key]+=1
    return amounts


def point_breakdown(trips,batches,prices,coordination):
    # RWB's comparison is booked once at final destination. A source or relay
    # earns a separate compensation for the operations actually scheduled there.
    rows={point:Counter() for point in STATIONS}
    batch_cost=Counter()
    served,relayed=set(),set()
    for trip in trips:
        route_ids=set()
        site_minutes=Counter()
        for visit in trip["stops"]:
            point=visit["point"]
            for event in visit["events"]:
                oid,kind,qty=event["batch"],event["kind"],event["qty"]
                route_ids.add(oid)
                rows[point][kind]+=qty
                if kind=="drop":
                    served.add(oid)
                if kind=="relay_drop":
                    relayed.add(oid)
            if visit["events"]:
                site_minutes[point]+=16+sum(event["qty"] for event in visit["events"])
        for point,quarters in site_minutes.items():
            rows[point]["work_quarters"]+=quarters
        work_payout=split_cost(trip["costs"]["pvz"],site_minutes)
        for point,payout in work_payout.items():
            rows[point]["work_payout"]+=payout
        weights={oid:batches[oid]["qty"] for oid in route_ids}
        batch_cost.update(split_cost(sum(trip["costs"].values()),weights))
    batch_cost.update(split_cost(coordination,{oid:batches[oid]["qty"] for oid in served}))
    parcel_cost=sum(round(prices[key]*100) for key in ("packing","rebate","expected_extra_risk"))
    for oid,batch in batches.items():
        units=batch["qty"]
        row=rows[batch["to"]]
        baseline=estimate_hub(batch,prices)
        row["requested"]+=units
        row["baseline"]+=baseline
        if oid in served:
            row["actual"]+=batch_cost[oid]+units*parcel_cost
            row["rebate"]+=units*round(prices["rebate"]*100)
            if oid in relayed:
                row["actual"]+=units*round(prices["transfer_handling"]*100)
        else:
            row["actual"]+=baseline
            row["hub"]+=units
    result=[]
    for point,row in rows.items():
        work_min=row["work_quarters"]/4
        transfer=row["relay_drop"]
        revenue=row["work_payout"]+transfer*round(prices["transfer_handling"]*100)
        cost=round(work_min/60*prices["pvz_internal_hour"]*100)+transfer*round(prices["transfer_internal"]*100)
        if point=="HUB" and not (row["requested"] or work_min):
            continue
        result.append({"point":point,"requested":row["requested"],"hub":row["hub"],
            "pickup":row["pickup"],"drop":row["drop"],"relay_drop":transfer,"relay_pickup":row["relay_pickup"],
            "work_minutes":work_min,"baseline":row["baseline"],"actual":row["actual"],
            "rwb_effect":row["baseline"]-row["actual"],"seller_rebate":row["rebate"],
            "pvz_revenue":revenue,"pvz_cost":cost,"pvz_margin":revenue-cost})
    return result


def plan(vehicles,batches,prices,allow_transfer=True):
    def best(transfer):
        return min((solve(vehicles,batches,prices,transfer,volume_first) for volume_first in (False,True)),
                   key=lambda variant:variant["economics"]["total"])
    direct=best(False)
    with_relay=best(True) if allow_transfer else direct
    chosen=min((with_relay,direct),key=lambda variant:variant["economics"]["total"])
    gross=chosen["economics"]["savings"]
    coordination=round(prices["coordination_day"]*100)
    if 0<gross<=coordination:
        available=[v for v in vehicles if v["start_min"]+minutes(v["start"],v["end"])<=v["end_min"]]
        empty=schedule([[(v["start"],[]),(v["end"],[])] for v in available],available,batches,prices)
        chosen={"trucks":empty,"economics":summarize(empty,batches,prices)}
    economy=chosen["economics"]
    day_fee=coordination if economy["units"] else 0
    economy.update(total=economy["total"]+day_fee,savings=economy["savings"]-day_fee,
                   coordination=day_fee,active_trial_delta=gross-coordination)
    if economy["units"]:
        economy["break_even_per_unit"]=(economy["direct_cost"]+day_fee)/economy["units"]
    no_relay=direct["economics"]
    no_relay_total=min(no_relay["all_hub"],no_relay["total"]+(coordination if no_relay["units"] else 0))
    # The chosen variant can be the same object as the direct-only variant.
    if no_relay is economy:
        no_relay_total=economy["total"]
    economy["by_pvz"]=point_breakdown(chosen["trucks"],batches,prices,day_fee)
    return {**chosen,"batches":batches,"prices":prices,"without_relay":no_relay_total}
