# solver.py
from models import ModelConfig, CostWeights
from state import SolutionState
from greedy import build_initial_solution
from search import simulated_annealing


# io_utils.py
def load_problem(schedule_path, nodes_path, distances_path, roads_path):
    blocks = load_blocks(schedule_path)
    nodes = load_nodes(nodes_path)
    distances = load_distances(distances_path)
    roads = load_roads(roads_path)

    return blocks, nodes, distances, roads

def main():
    config = ModelConfig()
    weights = CostWeights()

    # 1. 데이터 읽기 + 후보 적치장 생성
    blocks, yards, options = load_problem()

    # 2. 배정·사용 면적·비용을 관리할 상태 생성
    state = SolutionState(
        blocks=blocks,
        yards=yards,
        options=options,
        config=config,
        weights=weights,
    )

    # 3. 그리디로 초기 배정
    build_initial_solution(state)

    # 4. 초기해를 기반으로 개선
    best = simulated_annealing(
        state,
        time_limit_seconds=60,
        seed=42,
    )

    # 5. 결과 검증·저장
    validate_solution(best)
    write_solution(best)


if __name__ == "__main__":
    main()