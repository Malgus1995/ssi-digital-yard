import argparse
import json
from pathlib import Path

from ssi_yard.data.load_scenario import load_scenario
from ssi_yard.data.prepare_milp import prepare_milp_inputs
from ssi_yard.planners.milp.planner import plan
from ssi_yard.benchmark.results import create_daily_moves, save_result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data-dir", type=Path, default=Path("raw-data")
    )
    parser.add_argument(
        "--config", type=Path, default=Path("scenarios/milp.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("runs/milp/result.json")
    )
    args = parser.parse_args()

    with args.config.open(encoding="utf-8") as file:
        config = json.load(file)

    scenario = load_scenario(args.data_dir)

    inputs = prepare_milp_inputs(
        scenario,
        spacing_factor=config["spacing_factor"],
        max_utilization=config["max_utilization"],
        movement_rate_per_m=config["movement_rate_per_m"],
    )

    yard_rate = {}
    tier_by_yard = {}

    for yard_code in inputs["capacity"]:
        override = config["yard_overrides"].get(yard_code, {})

        yard_rate[yard_code] = override.get(
            "yard_rate", config["default_yard_rate"]
        )
        tier_by_yard[yard_code] = override.get(
            "tier", config["default_tier"]
        )

    # JSON 객체의 키는 문자열이므로 단계 번호를 정수로 바꾼다.
    threshold_by_tier = {
        int(k): value
        for k, value in config["threshold_by_tier"].items()
    }
    congestion_rate = {
        int(k): value
        for k, value in config["congestion_rate"].items()
    }

    result = plan(
        **inputs,
        max_utilization=config["max_utilization"],
        spacing_factor=config["spacing_factor"],
        yard_rate=yard_rate,
        tier_by_yard=tier_by_yard,
        threshold_by_tier=threshold_by_tier,
        congestion_rate=congestion_rate,
    )

    if result is None:
        return

    assignment, total_cost = result
    daily_moves = create_daily_moves(inputs["blocks"], assignment)

    save_result(
        output_path=args.output,
        assignment=assignment,
        daily_moves=daily_moves,
        total_cost=total_cost,
    )
    print(f"결과 저장 완료 {args.output}")


if __name__ == "__main__":
    main()