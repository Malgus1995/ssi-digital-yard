import json
import os
import tempfile
from pathlib import Path
from collections import defaultdict
from ssi_yard.domain import Block

def create_daily_moves(
    blocks: dict[str, Block],
    assignment: dict[str, str],
) -> dict[str, list[dict[str, str]]]:
    daily_moves = defaultdict(list)

    for block_code, block in blocks.items():
        inbound_day = block.inbound_date.isoformat()
        outbound_day = block.outbound_date.isoformat()

        # 당일 출고 블록은 공장에서 다음 공장으로 직행한다.
        if not block.requires_yard:
            daily_moves[inbound_day].append({
                "block": block_code,
                "from": block.inbound_factory,
                "to": block.outbound_factory,
                "action": "직행",
            })
            continue

        yard_code = assignment[block_code]

        daily_moves[inbound_day].append({
            "block": block_code,
            "from": block.inbound_factory,
            "to": yard_code,
            "action": "입고",
        })

        daily_moves[outbound_day].append({
            "block": block_code,
            "from": yard_code,
            "to": block.outbound_factory,
            "action": "출고",
        })

    return dict(sorted(daily_moves.items()))

def save_result(
    output_path: Path,
    assignment: dict[str, str],
    daily_moves: dict[str, list[dict[str, str]]],
    total_cost: float,
) -> None:
    result = {
        "total_cost": total_cost,
        "assignment": assignment,
        "daily_moves": daily_moves,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output_path.parent,
                                         prefix=output_path.name + '.', suffix='.tmp', delete=False) as file:
            temporary = file.name
            json.dump(result, file, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temporary, output_path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
