# 일별 적치장 뷰어

Node.js로 실행하는 로컬 웹 화면입니다. 외부 패키지나 CDN이 필요하지 않습니다.

```bash
# 프로젝트 루트에서 결과와 일별 스냅샷 생성
.venv/bin/python main.py --methods or --limit 500 --time-limit-seconds 30

# 로컬 서버 시작
npm start
```

프로젝트 루트에서 `npm start` 또는 `npm run dev`로 실행합니다.
`yard-viewer` 폴더 안에서도 `npm start`를 사용할 수 있습니다.
서버 종료는 실행한 터미널에서 `Ctrl+C`를 누릅니다. 솔버는 자동 실행하지 않습니다.

http://localhost:3000 에 접속합니다. 포트 변경: `PORT=3001 npm start`.

- 실행 결과 선택, 날짜 선택·슬라이더·자동 재생
- 입고/출고 경로, 적치장 선택, 이용률과 적치 블록 확인
- 블록 코드 검색, 해당 날짜 스냅샷 JSON 다운로드
- `runs/<실행명>/<방법>/snapshots/YYYY-MM-DD.json`에 일별 상태와 이동 이벤트 저장
- 이전 실행 결과도 최초 조회 시 스냅샷 자동 생성
- `data/solution`의 직접 실행 결과도 조회 가능

입고는 선행 공장 → 적치장, 출고는 적치장 → 다음 공장입니다.
일별 점유는 `inbound_date <= day < outbound_date` 기준이며 당일 입출고도 두 이동 이벤트를 남깁니다.
지도는 GPS 노드 연결 개략도입니다. 실제 도로 경로나 시간대별 이동 순서를 나타내지 않습니다.
실행 결과를 같은 디렉터리에 수동 덮어쓴 경우 `python -m experiment.snapshots --output-dir <결과폴더> --nodes <노드CSV>`로 다시 생성하세요.
