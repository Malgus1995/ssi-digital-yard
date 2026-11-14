import argparse
from pathlib import Path

from ssi_yard.data.load_scenario import load_scenario


def main():
    parser = argparse.ArgumentParser(description="Validate SSI Digital Yard scenario inputs")
    parser.add_argument("--data-dir", type=Path, default=Path("raw-data"))
    args = parser.parse_args()
    scenario = load_scenario(args.data_dir)
    waiting = sum(block.requires_yard for block in scenario.blocks)
    yards = sum(node.kind == "적치장" for node in scenario.nodes.values())
    print(f"블록 {len(scenario.blocks):,}개 (야드 대기 {waiting:,}개, 직행 {len(scenario.blocks)-waiting:,}개)")
    print(f"적치장 {yards}개 · 공장 {len(scenario.nodes)-yards}개 · 도로 {len(scenario.roads)}개 · 거리표 {len(scenario.baselines)}개")


if __name__ == "__main__":
    main()
