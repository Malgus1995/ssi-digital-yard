# Experiment runner

루트의 `main.py`가 OR, SA, RL 솔버를 동일한 입출력 계약으로 실행합니다.

## 솔버 출력 계약

각 솔버는 전달받은 `--output-dir`에 다음 파일을 생성해야 합니다.

- `optimized_assignments.csv`
- `daily_yard_utilization.csv`
- `solution_summary.json`

비용을 공정하게 비교하려면 배정 CSV에 `transport_score`,
`first_fit_rank`가 있어야 합니다. 이용률 CSV에는
`date`, `yard_code`, `active_blocks`, `used_area_m2`, `usable_area_m2`,
`utilization`이 필요합니다.

배정 CSV는 모든 블록을 유지하며 `storage_mode`는 `STOCKYARD`입니다.
당일 입출고 블록도 적치장에 배정하지만 일별 점유 면적에는 포함하지 않습니다.

현재 OR 어댑터는 `milp-solver/solver.py`에 연결되어 있습니다. 향후 아래
경로에 같은 CLI 계약의 파일을 추가하면 `main.py --methods all`에 자동으로
포함됩니다.

- `meta-heuristic-solver/solver.py`
- `rl-solver/solver.py`

GIF에는 Pillow, MP4에는 Pillow와 imageio-ffmpeg가 필요합니다.
