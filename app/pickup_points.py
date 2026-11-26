"""Connect all pickup points on the road map to the original shift service."""

import json

import desk
import operations
import routing
from common import Problem
from truck_routes import RATES, STATIONS, distance, travel_ms

POINTS = {key: point for key, point in STATIONS.items() if key != "HUB"}


def is_rural(point):
    return POINTS[point]["area"] != "Город"


CAPACITY = {key: 120 if is_rural(key) else 240 for key in POINTS}
_original_capacity = desk.capacity
_original_settings = routing.default_settings
_original_central = operations._central


def capacity(point):
    return CAPACITY[point] if point in CAPACITY else _original_capacity(point)


def default_settings(source="A", destination="B"):
    settings = _original_settings(source, destination)
    if settings["hub_slots"] is not None or source not in POINTS or destination not in POINTS:
        return settings
    if source == destination:
        return settings

    rural = is_rural(source) or is_rural(destination)
    defaults = _original_settings("C", "D") if rural else _original_settings("A", "B")
    keys = ("dedicated_slots", "dedicated_liters", "dedicated_grams", "hub_slots", "hub_liters",
            "hub_grams", "origin_minutes", "destination_minutes", "destination_open", "origin_open",
            "hub_ready_hours")
    settings.update({key: defaults[key] for key in keys})
    settings.update(
        shared_slots=0, shared_liters=0, shared_grams=0, destination_liters=CAPACITY[destination],
        roundtrip_fixed=RATES["dedicatedFixed"] + round(2 * distance(source, destination) * RATES["km"]),
        dedicated_ready_hours=round(2 + travel_ms(source, destination) / 3600000, 2),
        hub_per_unit=RATES["ruralHub" if rural else "cityHub"],
    )
    return settings


def central_contribution(order):
    reference = _original_central(order)
    route = order["source"], order["destination"]
    if reference is not None and "D" not in route and any(is_rural(point) for point in route):
        # The original comparison applies 14,600 kopecks in place of 10,000 on rural routes via D.
        reference -= 4600
    return reference


def change_direction(db, body):
    if desk.get(db, "scenario") != "sandbox":
        raise Problem(409, "FIXED_SCENARIO", "Свободный выбор направления доступен в свободной смене.")
    source, destination = body["source"], body["destination"]
    if source not in POINTS or destination not in POINTS or source == destination:
        raise Problem(422, "UNKNOWN_DIRECTION", "Выберите два разных пункта выдачи.")
    old = desk.get(db, "settings")
    desk.put(db, "lane-" + old["source"] + old["destination"], old)
    key = "lane-" + source + destination
    row = db.execute("SELECT value FROM desk_meta WHERE key=?", (key,)).fetchone()
    settings = json.loads(row[0]) if row else default_settings(source, destination)
    version = desk.get(db, "version") + 1
    desk.put(db, "settings", settings)
    desk.put(db, "version", version)
    desk.put(db, "quote_id", None)
    desk.refresh(db)
    return {"window_id": desk.window_id(settings), "version": version}


def connect_shift():
    # These registries are read by the packaged shift modules for both new and saved workdays.
    operations.POINT_CAPACITY.update(CAPACITY)
    desk.NAMES.update({key: point["title"] for key, point in POINTS.items()})
    desk.COORDS.update({key: (100 * point["x"] / 1040, 100 * point["y"] / 510)
                        for key, point in POINTS.items()})
    desk.capacity = capacity
    operations._central = central_contribution
    routing.default_settings = default_settings
