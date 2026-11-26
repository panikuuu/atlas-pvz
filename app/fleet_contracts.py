"""Day-level contribution and contract ranges, with all money in kopecks."""

from collections import Counter, defaultdict

from fleet import FIXTURE, split_cost


DEFAULT_TARGETS = {"rwb_per_order": 100, "seller_per_order": 100, "pvz_per_day": 100}


def targets_for(changes):
    if not isinstance(changes, dict) or any(
        key not in DEFAULT_TARGETS or type(value) is not int or not 1 <= value <= 1000000
        for key, value in changes.items()
    ):
        raise ValueError("Укажите целевой вклад от 0,01 до 10 000 ₽.")
    return DEFAULT_TARGETS | changes


def contract_for(profile):
    if not isinstance(profile, str) or profile not in FIXTURE["contracts"]:
        raise ValueError("Выберите исходный или пилотный договор.")
    return FIXTURE["contracts"][profile]


def margin_rows(rows, key):
    grouped = defaultdict(Counter)
    for row in rows:
        group = grouped[row[key]]
        group.update(orders=1, direct=int(row["channel"] == "fleet"), revenue=row["price"],
                     goods=row["cost"], logistics=row["tariff"], commission=row["commission"],
                     profit=row["seller_profit"], rwb_profit=row["rwb_profit"])
    return [{"id": group, **totals} for group, totals in sorted(grouped.items())]


def seller_ranges(rows, targets, hub_tariff):
    groups = defaultdict(list)
    for row in rows:
        groups[row["seller"], row["to"], row["channel"]].append(row)
    result = []
    for (seller, point, channel), orders in sorted(groups.items()):
        count = len(orders)
        paid = sum(row["tariff"] for row in orders)
        required = sum(row["physical_cost"] - row["commission"] - row["buyer_delivery"] for row in orders)
        available = sum(row["price"] - row["cost"] - row["commission"] for row in orders)
        low = max(0, -(-required // count) + targets["rwb_per_order"])
        high = available // count - targets["seller_per_order"]
        if channel == "fleet":
            high = min(high, hub_tariff)
        suggested = min(max(paid // count, low), high) if low <= high else None
        result.append({"seller": seller, "point": point, "channel": channel, "orders": count,
                       "skus": sorted({row["sku"] for row in orders}), "current": paid // count,
                       "minimum": low, "maximum": high, "recommended": suggested,
                       "rwb_profit": suggested * count - required if suggested is not None else None,
                       "seller_profit": available - suggested * count if suggested is not None else None})
    return result


def pvz_ranges(points, prices, headroom, target):
    active = {row["point"]: row for row in points if row["work_minutes"]}
    current = round(prices["pvz_hour"] * 100)
    weights = {point: round(row["work_minutes"] * 4) for point, row in active.items()}
    minimum_bill = {
        point: max(0, row["pvz_cost"] + target - row["relay_drop"] * round(prices["transfer_handling"] * 100))
        for point, row in active.items()
    }
    payments = {point: row["pvz_revenue"] - row["relay_drop"] * round(prices["transfer_handling"] * 100)
                for point, row in active.items()}
    minimum_rates = {point: -(-bill * 240 // weights[point]) for point, bill in minimum_bill.items()}
    minimum_payments = {point: round(weights[point] * rate / 240) for point, rate in minimum_rates.items()}
    surplus = headroom + sum(payments.values()) - sum(minimum_payments.values())
    allocations = split_cost(max(0, surplus), weights)
    result = []
    for point, quarters in weights.items():
        low = minimum_rates[point]
        max_payment = minimum_payments[point] + allocations[point]
        high = max_payment * 240 // quarters if surplus >= 0 else None
        if high is not None:
            high = max(low, high)
        suggested = min(max(current, low), high) if high is not None else None
        result.append({"point": point, "minutes": quarters / 4, "current": current, "minimum": low,
                       "maximum": high, "recommended": suggested,
                       "profit": (round(quarters * suggested / 240) + active[point]["relay_drop"] *
                                  round(prices["transfer_handling"] * 100) - active[point]["pvz_cost"])
                                 if suggested is not None else None})
    return result


def report(plan, profile, targets):
    prices, economy = plan["prices"], plan["economics"]
    hub_tariff = contract_for(profile)["hub_tariff"]
    orders = []
    for batch in plan["batches"].values():
        route = batch["route"]
        rebate = min(hub_tariff, round(prices["rebate"] * 100)) if route else 0
        tariff = hub_tariff - rebate
        allocation = split_cost(batch["physical_cost"], {order["id"]: 1 for order in batch["orders"]})
        for order in batch["orders"]:
            cost = allocation[order["id"]]
            commission = (order["price"] * 15 + 50) // 100
            orders.append({
                **order, "batch": batch["id"], "from": batch["from"], "to": batch["to"],
                "ready": batch["ready"], "channel": "fleet" if route else "hub",
                "route": route, "commission": commission, "tariff": tariff, "physical_cost": cost,
                "rwb_profit": commission + tariff + order["buyer_delivery"] - cost,
                "seller_profit": order["price"] - order["cost"] - commission - tariff,
            })
    rwb = sum(row["rwb_profit"] for row in orders)
    return {
        "profile": profile, "targets": targets, "orders": orders,
        "rwb_revenue": sum(row["commission"] + row["tariff"] + row["buyer_delivery"] for row in orders),
        "rwb_cost": sum(row["physical_cost"] for row in orders), "rwb_profit": rwb,
        "seller_profit": sum(row["seller_profit"] for row in orders),
        "pvz_profit": sum(row["pvz_margin"] for row in economy["by_pvz"]),
        "by_seller": margin_rows(orders, "seller"),
        "seller_rates": seller_ranges(orders, targets, hub_tariff),
        "pvz_rates": pvz_ranges(economy["by_pvz"], prices,
                               rwb - targets["rwb_per_order"] * len(orders), targets["pvz_per_day"]),
    }
