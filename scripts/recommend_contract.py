"""Calculate contract thresholds for a synthetic day or an exported fleet plan."""

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import fleet
import fleet_contracts


def kopecks(value):
    try:
        rubles = Decimal(value)
        if rubles.is_finite() and Decimal("0.01") <= rubles <= 10000:
            amount = rubles * 100
            if amount == amount.to_integral_value():
                return int(amount)
    except InvalidOperation:
        pass
    raise argparse.ArgumentTypeError("Введите сумму от 0.01 до 10000 ₽ с точностью до копейки.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--scenario", choices=fleet.FIXTURE["scenarios"], default="assortment")
    inputs.add_argument("--from-plan", type=Path, help="JSON из раздела «Парк машин»")
    parser.add_argument("--contract", choices=fleet.FIXTURE["contracts"], help="Для синтетического сценария")
    parser.add_argument("--rwb-min", type=kopecks, help="Целевой вклад RWB за заказ, ₽")
    parser.add_argument("--seller-min", type=kopecks, help="Целевой вклад продавца за заказ, ₽")
    parser.add_argument("--pvz-min", type=kopecks, help="Целевая маржа каждого ПВЗ за день, ₽")
    args = parser.parse_args()

    try:
        if args.from_plan:
            if args.contract:
                parser.error("Для другого договора пересчитайте маршрут и экспортируйте новый план.")
            plan = json.loads(args.from_plan.read_text(encoding="utf-8-sig"))
            if "plan" in plan:
                plan = plan["plan"]
            profile = plan["financials"]["profile"]
            saved_targets = plan["financials"]["targets"]
        else:
            profile = args.contract or "pilot"
            preset = fleet.FIXTURE["scenarios"][args.scenario]
            trucks = fleet.validate_vehicles(preset["trucks"])
            rates = fleet.prices_for({"rebate": fleet_contracts.contract_for(profile)["rebate"]})
            plan = fleet.plan(trucks, fleet.demo_batches(preset, trucks), rates,
                              bays=preset.get("bays", len(trucks)))
            saved_targets = {}
        overrides = {"rwb_per_order": args.rwb_min, "seller_per_order": args.seller_min,
                     "pvz_per_day": args.pvz_min}
        targets = fleet_contracts.targets_for(saved_targets | {k: v for k, v in overrides.items() if v is not None})
        report = fleet_contracts.report(plan, profile, targets)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        parser.error(f"Не удалось рассчитать договор: {exc}")

    sys.stdout.reconfigure(encoding="utf-8")
    summary = {key: value for key, value in report.items() if key != "orders"}
    print(json.dumps({"currency": "RUB", "amount_unit": "kopeck", **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
