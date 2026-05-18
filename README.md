# Bizline OpenDART/KIND 테스트 수집기

엑셀에 있는 `사업자등록번호`와 `업체명`만으로 OpenDART 매칭 정보, OpenDART 공시, KIND 시장조치 정보를 테스트 수집하는 최소 유틸리티입니다.
NICE, 국세청 휴폐업, 리스크 평가 테이블은 수집하지 않습니다.

## 입력 엑셀 형식

첫 번째 시트에 아래 컬럼명이 있으면 자동 인식합니다.

| 필수 값 | 인식 컬럼명 예시 |
| --- | --- |
| 사업자등록번호 | `사업자등록번호`, `사업자번호`, `biz_no` |
| 업체명 | `업체명`, `회사명`, `거래처명`, `customer_name` |

사업자등록번호는 하이픈이 있어도 되며, 내부적으로 숫자 10자리로 정규화합니다.

## 실행 방법

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export OPENDART_API_KEY="발급받은_OpenDART_인증키"
python -m risk_sources.collector --excel ./customers.xlsx --output-dir ./out/risk_sources
```

또는 설치 후 콘솔 스크립트를 사용할 수 있습니다.

```bash
pip install -e .
bizline-collect-risk-sources --excel ./customers.xlsx --output-dir ./out/risk_sources
```


## Visual Studio Code에서 실행하기

1. VS Code에서 이 저장소 폴더(`/workspace/bizline`)를 엽니다.
2. 왼쪽 **Run and Debug** 패널을 열거나 `Ctrl+Shift+D`를 누릅니다.
3. 실행 구성에서 **OpenDART/KIND 수집 실행**을 선택합니다.
4. `F5`를 누르면 아래 값을 차례대로 입력하라는 창이 뜹니다.
   - 엑셀 또는 CSV 파일 경로: 예) `${workspaceFolder}/customers.xlsx`
   - 결과 저장 폴더: 예) `${workspaceFolder}/out/risk_sources`
   - OpenDART 공시 조회 기간: 기본값 `365`
   - OpenDART 인증키: 발급받은 인증키 입력
5. 실행이 끝나면 결과 저장 폴더에서 `result.json`, `dart_companies.csv`, `dart_disclosures.csv`, `kind_market_events.csv`를 확인합니다.

VS Code 실행 설정은 `.vscode/launch.json`에 들어있습니다. 인증키는 파일에 저장하지 않고 실행할 때마다 입력하도록 구성했습니다.

### VS Code 터미널에서 직접 실행하기

VS Code 하단 터미널에서도 아래처럼 실행할 수 있습니다.

```bash
cd /workspace/bizline
export OPENDART_API_KEY="발급받은_OpenDART_인증키"
PYTHONPATH=src python3 -m risk_sources.collector --excel ./customers.xlsx --output-dir ./out/risk_sources
```

## 출력 파일

`--output-dir` 아래에 다음 파일을 생성합니다.

- `result.json`: 전체 결과(JSON)
- `dart_companies.csv`: `dart_companies` 테이블에 대응되는 OpenDART 기업 매칭 결과
- `dart_disclosures.csv`: `dart_disclosures` 테이블에 대응되는 OpenDART 공시 결과
- `kind_market_events.csv`: `kind_market_events` 테이블에 대응되는 KIND 시장조치 결과
- `.cache/dart_corp_codes.json`: OpenDART 고유번호 ZIP 파싱 캐시

## 수집 범위

1. OpenDART `corpCode.xml`을 내려받아 업체명으로 후보를 찾습니다.
2. OpenDART `company.json` 기업개황의 `bizr_no`와 엑셀 사업자등록번호를 교차 검증합니다.
3. 검증된 `corp_code`로 OpenDART `list.json` 최근 공시를 수집합니다.
4. 검증된 `stock_code`가 있으면 KIND 공개 페이지를 조회해 관리종목, 거래정지, 상장폐지 관련 시장조치 행을 추출합니다.

KIND 시장조치는 OpenDART처럼 인증키 기반 JSON API가 아니라 공개 HTML 화면을 best-effort로 파싱합니다. 테스트 중 KIND 화면 구조가 바뀌면 `KindClient.EVENT_ENDPOINTS` 또는 `parse_kind_html`을 조정하면 됩니다.
