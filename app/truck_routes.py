"""Distances and comparative costs for the offline road network."""

from functools import lru_cache
from heapq import heappop, heappush
from itertools import pairwise
import json
from math import hypot
from pathlib import Path

NETWORK = json.loads((Path(__file__).parent / "static" / "roads.json").read_text(encoding="utf-8"))
STATIONS = NETWORK["stations"]
RATES = NETWORK["rates"]
SAMPLE_LANES = ("FA", "FB", "AE", "EG", "BC", "BJ", "GD", "CD", "CK", "JK", "DK")
GRAPH = {}
for source, destination, bends in NETWORK["roads"]:
    points = STATIONS | NETWORK["junctions"]
    a, b = points[source], points[destination]
    coords = [(a["x"], a["y"]), *bends, (b["x"], b["y"])]
    km = sum(hypot(x2-x1, y2-y1) for (x1, y1), (x2, y2) in pairwise(coords)) * NETWORK["scaleKm"]
    GRAPH.setdefault(source, []).append((destination, km))
    GRAPH.setdefault(destination, []).append((source, km))


@lru_cache(maxsize=100)
def distance(source, destination):
    if source not in STATIONS or destination not in STATIONS:
        raise ValueError("Unknown road endpoint")
    pending = [(0.0, source)]
    visited = set()
    while pending:
        km, point = heappop(pending)
        if point == destination:
            return km
        if point not in visited:
            visited.add(point)
            for neighbor, length in GRAPH.get(point, ()):
                if neighbor not in visited:
                    heappush(pending, (km + length, neighbor))
    raise ValueError("Disconnected road network")


def road_distance(source, destination):
    try:
        return distance(source, destination)
    except ValueError:
        return None


def travel_ms(source, destination):
    return round(distance(source, destination) / NETWORK["speedKmh"] * 3_600_000)


def sample_orders(departure):
    return {
        f"Т-{index + 1:02}": {
            "id": f"Т-{index + 1:02}", "from": lane[0], "to": lane[1],
            "liters": 2 + index % 3, "grams": 600 + 200 * (index % 3),
            "due": departure + (240 if index < 3 else 360) * 60_000,
        }
        for index, lane in enumerate(SAMPLE_LANES)
    }


def comparison(points, orders, service_minutes, profile):
    legs = list(pairwise(points))
    km = sum(distance(a, b) for a, b in legs)
    base = distance(points[0], points[-1])
    discount = (1000 if profile == "original" else RATES["sellerDiscount"]) * len(orders)
    operating = round(max(0, km - base) * RATES["km"]) + service_minutes * RATES["stopMinute"]
    lanes = {(o["from"], o["to"]) for o in orders}
    separate = sum(RATES["dedicatedFixed"] + round(2 * distance(a, b) * RATES["km"])
                   for a, b in lanes)
    separate += (8 * len(lanes) + 2 * len(orders)) * RATES["stopMinute"] + discount
    hub = sum(
        RATES["ruralHub"] if any(STATIONS[p]["area"] in {"Село", "Деревня", "Посёлок"}
                               for p in (o["from"], o["to"])) else RATES["cityHub"]
        for o in orders
    )
    contribution = [0] * len(points)
    for i in range(1, len(points) - 1):
        a, b, c = points[i-1:i+2]
        contribution[i] = round(max(0, distance(a,b)+distance(b,c)-distance(a,c))*RATES["km"])
    return {"km": km, "extra_km": max(0, km-base), "operating": operating,
            "multi": operating+discount, "separate": separate, "hub": hub, "per_stop": contribution}
