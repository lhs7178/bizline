# RiskManagement 프로젝트 설계 문서

> 이 문서는 개발 진행에 따라 지속적으로 업데이트합니다.  
> 프로젝트명: RiskManagement | DB: Supabase PostgreSQL | 배포: Render | VCS: GitHub

---

## 보완 요약

- 원문에 중복으로 포함되어 있던 `DESIGN.md` 전체 반복 내용을 제거했습니다.
- `DB.md` 보강 사항을 설계 문서에도 반영했습니다: 사업자번호 10자리 정규화, `CHECK` 제약 기반 상태값, `updated_at` 자동 갱신, FK 삭제 정책, 최신 조회용 인덱스 전제.
- `nice_scraping_staging.status` 값을 `pending | applied | skipped | failed`로 명확히 하고, `applied` 상태에서는 `applied_at` 기록을 필수로 정의했습니다.
- DART `no_match`를 고려해 `dart_companies.corp_code`는 매칭 성공 시에만 저장하며, `corp_code IS NOT NULL` 조건 unique index 전제를 설계에 반영했습니다.
- 수집/업로드 로그 상태값을 DB 제약과 맞춰 `running | success | failed | partial`, `pending | success | failed | partial`로 정리했습니다.
- Supabase 운영 전제인 RLS, `.env`, 원본 JSONB 보관/마스킹, Supabase Auth 연동 검토 사항을 추가했습니다.

---

## 1. 프로젝트 개요

거래처의 신용위험·공시 리스크·휴폐업 상태를 통합 관리하는 웹 시스템입니다.  
매주 수동으로 엑셀 스크래핑하던 방식을 **DB 중심 웹 관리 + Staging 승인 흐름**으로 전환합니다.

**기술 스택**

| 구분 | 내용 |
|---|---|
| Frontend | React 또는 Next.js(개발자 결정) |
| Backend | FastAPI 또는 Next.js API Routes |
| DB | Supabase PostgreSQL |
| Auth | Supabase Auth 또는 자체 사용자 테이블 연동 방식 검토 |
| 배포 | Render |
| 버전관리 | Git / GitHub(공동 운영) |

**데이터 소스**

| 구분 | 대상 | 방식 |
|---|---|---|
| 스크래핑 | NICE BIZLINE | Playwright 중심. 서버/로컬 실행 방식은 봇 차단 테스트 후 결정 |
| 스크래핑 | 한국거래소 KIND | Playwright 또는 requests. 실제 화면/API 구조 확인 후 결정 |
| API | OpenDART | REST API(키 보유) |
| API | 국세청 휴폐업 | data.go.kr REST API(키 보유) |

**핵심 데이터 원칙**

1. `biz_no`는 모든 저장 전에 하이픈·공백을 제거한 **10자리 숫자 문자열**로 정규화합니다.
2. 거래처는 삭제하지 않고 `current_status`로 관리합니다.
3. API/스크래핑 원본은 감사·디버깅을 위해 `raw_data jsonb`에 저장하되, 민감정보는 마스킹합니다.
4. 운영 DB에서는 Supabase RLS를 활성화하고 `admin`/`user` 권한별 정책을 분리합니다.

---

## 2. 현재 업무 프로세스(전환 전)

담당자는 매주 아래 4개 그룹의 관리 대상 업체를 파악하여 NICE BIZLINE에 등록합니다.

| 그룹 |
|---|
| 외상매출금 |
| 대리점 / 지정점 |
| A/S 미수금 |
| 어음 / 출하 후 세금계산서 미발행 |

거래처 등록 시 **사업자등록번호 + 거래처명**은 필수이고, 거래처코드는 선택입니다.  
기존에는 매주 `NICE_BIZLINE_BIZNO_SCRAPER.py`를 실행하여 엑셀로 수집 후 관리했습니다.

**기존 스크래퍼 수집 항목:** 거래처명, 거래처코드, 사업자등록번호, 대표자명, 개업일자, 표준산업분류, 종업원수, 기업평가, WATCH, 현금흐름, 연체정보, 주소, 전화번호

---

## 3. 신규 데이터 수집 프로세스(전환 후)

### 3.1 NICE BIZLINE 수집 흐름

```text
[웹 대시보드] '데이터 가져오기' 버튼 클릭
  → data_import_logs에 import_type='NICE', status='running' 기록
  → 백그라운드 Job 시작 + 진행 상태 표시(n / 전체)
  → Playwright로 NICE BIZLINE 로그인 → 4개 그룹 거래처 순회
  → 업체 1개 수집 즉시 nice_scraping_staging에 row-by-row INSERT
     - session_id로 실행 단위 묶음
     - biz_no는 10자리 숫자로 정규화
     - status 기본값은 'pending'

수집 완료 후 자동 분석 엔진 실행(백그라운드)
  → staging 데이터를 customers와 biz_no 기준 비교
      신규발생: DB에 없는 거래처 → 신규 등록 대상(is_new_customer=true)
      기존고객: DB에 이미 있는 거래처(current_status 무관)
  → diff_data 생성
      예: {"ceo_name": {"old": "홍길동", "new": "김철수"}}
  → 신규발생 거래처만 국세청 즉시 조회(폐업 여부 사전 확인)
  → 신규발생 거래처만 DART 매칭 시작(백그라운드, 완료 기다리지 않음)

관리자 Staging 검토 화면
  - 결과 요약: "신규발생 3건(폐업확인 0건) / 기존고객 12건"
  - 신규발생 거래처 목록 강조 표시
  - 기존고객 중 등급 변경·대표자·주소·전화번호 등 변경 항목 Diff 표시
  - DART 매칭 상태: 처리 중 / 완료 / 검토 필요 표시

관리자 확인 후 'DB에 저장' 버튼 클릭
  → customers upsert(biz_no 기준, 신규 INSERT or 기존 UPDATE)
  → nice_credit_snapshots upsert(customer_id + collected_date 기준)
  → customer_group_members 갱신
  → 대표자명·주소·전화번호 등 변경 감지 → change_alerts 생성
  → customers.last_collected_date / last_evaluation_grade / grade_trend 캐시 갱신
  → risk_rules 기반 risk_evaluations 생성 및 customers.current_risk_level 갱신
  → data_import_logs status='success' 또는 'partial'/'failed'로 마감
  → staging status='applied', applied_at=now() 기록

DB 저장 이후(백그라운드 계속 진행)
  → DART 매칭 완료 → dart_companies 업데이트
  → 매칭 완료 또는 review_required 발생 시 알림 표시
```

> **신규발생 판단 기준**: `biz_no` 기준으로 DB 확인. 과거에 등록됐던 거래처가 재등장해도 DB에 있으면 기존고객으로 처리합니다.

> **이탈 거래처 처리**: NICE에서 빠진 거래처는 삭제하지 않습니다. 다음 수집 시 목록에 없으면 `current_status = '과거 관리 대상'`으로 전환하고 검색 가능 상태를 유지합니다.

> **Staging 상태값**: `pending | applied | skipped | failed`. `applied` 상태에는 반드시 `applied_at`을 기록합니다.

### 3.2 NICE BIZLINE 스크래퍼 기술 메모

> 서버 배포 전 아래 항목을 반드시 확인 후 구현합니다.

| 항목 | 내용 |
|---|---|
| 라이브러리 | Selenium → **Playwright 전환 권장**(`playwright-stealth` 등은 실제 효과 검증 후 사용) |
| 실행 환경 | 로컬 Windows 실행 우선 검토. Render/Linux headless 실행은 봇 탐지와 브라우저 의존성 검증 후 결정 |
| 자격증명 | 하드코딩 ID/PW 금지. `.env` 환경변수 및 배포 환경 Secret 사용 필수 |
| 봇 탐지 위험 | 로컬 PC는 서버보다 탐지 위험이 낮을 수 있으나, 장기 운영 전 headless/서버 환경 테스트 필요 |
| 저장 방식 | 업체 1개 수집 완료 즉시 staging DB 저장(row-by-row). 중간 실패 시에도 이미 수집한 데이터 보존 |

**스크래퍼 재설계 방향(경량화)**

기존 스크래퍼는 재무제표·KPI·매입매출처·종합의견 등 방대한 정보를 수집했으나, 새 DB 설계에서는 아래 필드 중심으로 축소합니다.

| 구분 | 필드 |
|---|---|
| 거래처 기본 | 거래처명, 거래처코드, 사업자등록번호, 대표자명, 주소, 전화번호, 개업일자, 표준산업분류, 종업원수 |
| 신용평가 | 기업평가, WATCH, 현금흐름, 연체정보 |
| 수집 메타 | 그룹명, session_id, scraped_at, raw_data 일부 |

- **재활용**: 로그인, 그룹 탐색, 페이지네이션, 세션 관리, 재로그인, 배치 처리, 안티봇 로직
- **제거**: `extract_type_a` / `extract_type_b`의 재무·KPI·매입처 파싱 전체, Excel 다중 시트 생성 로직(`add_sheet_to_wb`)
- **신규**: 필수 필드만 추출하는 단일 경량 파서 + staging DB 직접 저장

**Type A / Type B 통합 파서 전략**

| 필드 그룹 | 공통 파싱 전략 |
|---|---|
| 기업명·대표자·사업자번호·주소·개업일 등 | `#section1` th/td 순회. 키 이름 차이(업체명↔기업명 등)는 키워드 포함 여부로 통합 처리 |
| 기업평가·WATCH·현금흐름 | Type A CSS(`.grade__info__item`) 먼저 시도 → 없으면 Type B(`#section2` table) fallback |
| 연체정보 | “미해제 10일이상 연체” 텍스트 탐색. Type B(SOHO)는 해당 항목 없음 → **NULL 저장**(빈 문자열 아님) |

NICE BIZLINE이 Vue.js SPA라면 `page.on("response")`로 내부 API 응답을 직접 가로채는 방식을 검토합니다. HTML 파싱보다 빠르고 안정적일 수 있으나, 실제 네트워크 구조는 개발자도구로 먼저 확인합니다.

**특정 거래처 선택 수집**

전체 실행 외에 특정 거래처 1건 또는 다수 선택 후 단독 재수집할 수 있습니다. NICE BIZLINE에 등록된 거래처만 대상으로 하며, 미등록 거래처 조회는 별도 기능으로 검토합니다.

### 3.3 OpenDART 수집 흐름(2차)

```text
[B-1. 매칭 작업] — 신규발생 거래처 감지 시 자동 실행(NICE 수집과 연계)
  → CORPCODE.xml 다운로드(월 1회 캐시, 이후 재사용)
  → 거래처명 정규화 → CORPCODE.xml 이름 매칭 → 후보 추출
  → 후보 있을 경우: company.json 호출 → bizr_no 대조 → 매칭 확정
  → 매칭 성공: dart_companies에 corp_code 저장, matched_by 기록
  → 자동 매칭 실패: matched_by='review_required', candidates JSONB 저장
  → DART에 없다고 판단: matched_by='no_match', corp_code는 NULL 허용

[B-2. 공시 수집 작업] — 주 1회 정기 실행(NICE 수집과 같은 날)
  → 대상: dart_companies에 corp_code가 있는 거래처만(no_match 제외)
  → 최초 수집: 최근 1년치 / 이후: 마지막 수집일 이후 신규 공시만
  → DS001 공시 목록 수집 → dart_disclosures 저장
       저장 필드: receipt_no, report_name, flr_nm, pblntf_ty, dart_url,
                 disclosure_date, risk_level, risk_reason, raw_data
  → DS005 주요사항보고서 36종 전체 수집 → risk_rules 기준 분류
  → DS002 감사의견: 결산월 기준 연 1회 수집
  → data_import_logs 기록
```

> **공시 표시 원칙**: 주의/위험 등급만 강조 표시하고 정상은 기본 숨김 처리합니다. 최신순으로 정렬하며, 클릭 시 DART 원문을 새 창으로 엽니다.

> **DB 제약 반영**: `dart_companies.corp_code`는 `no_match` 상태를 위해 nullable입니다. 단, 값이 있는 경우에는 `corp_code IS NOT NULL` 조건 unique index로 중복을 방지합니다.

### 3.4 국세청 휴폐업 수집 흐름(3차)

```text
[이벤트] 신규발생 거래처 감지 시 즉시 자동 실행(NICE 수집과 연계)
  → 신규발생 거래처 사업자번호 조회
  → business_status_checks에 checked_at과 raw_data 저장
  → 폐업 확인 시 관리자에게 즉시 경고 표시(DB 저장 전 Staging 화면)

[정기] 주 1회 — NICE 수집과 통합 실행(같은 날)
  → current_status = '현재 관리 중' 전체 거래처 대상
  → 사업자번호 100개씩 배치 API 호출
  → business_status_checks에 결과 저장
  → 폐업·휴업 감지 시:
       customers.current_risk_level 업데이트(폐업→위험, 휴업→주의)
       customers.closing_date 업데이트(폐업일자)
       상태 변경 시 change_alerts 생성
       risk_evaluations 생성
  → data_import_logs 기록
```

> **폐업 거래처 처리 원칙**: 삭제 금지. 필요 시 `current_status = '과거 관리 대상'`으로 전환하고 기본정보 화면에 폐업일자를 표시합니다.

---

## 4. 초기 데이터 마이그레이션

기존에 쌓인 주간 엑셀 파일들의 과거 신용평가 이력을 DB에 입력합니다. 웹 서비스 오픈 전 Python 스크립트로 수행하는 일회성 작업입니다.

**마이그레이션 대상 엑셀 파일 구조**

| 항목 | 내용 |
|---|---|
| 파일명 패턴 | `{그룹번호}.{그룹명}_part{n}_{YYYYMMDD}_{HHmm}.xlsx` |
| 날짜 추출 | 파일명에서 `YYYYMMDD` → `collected_date` |
| 그룹 추출 | 파일명 앞부분 → `customer_groups` 테이블 매핑 |
| 컬럼 | No, 거래처명, 거래처코드, 사업자번호, 대표자명, 개업일자, 표준산업분류, 종업원수, 기업평가, Watch, 현금흐름, 연체정보, 주소, 전화번호 |

**마이그레이션 로직**

1. `biz_no` 정규화: 하이픈·공백 제거 후 10자리 숫자 검증. 실패 row는 skip/error로 집계합니다.
2. `customers` — 사업자번호 기준 upsert. 최신 기본정보와 캐시 필드(`last_collected_date`, `last_evaluation_grade`, `grade_trend`)를 갱신합니다.
3. `customer_group_members` — 해당 그룹에 매핑하고 `first_seen_at`, `last_seen_at`을 갱신합니다.
4. `nice_credit_snapshots` — `UNIQUE(customer_id, collected_date)` 기준 upsert합니다.
5. `excel_upload_logs` — `pending | success | failed | partial` 상태와 전체·삽입·수정·스킵·오류 건수를 기록합니다.

> 마이그레이션 스크립트 위치: `scripts/migrate_excel.py`(향후 작성)

---

## 5. 개발 우선순위

### 1차 개발 — NICE 스크래핑 + 화면

1. 초기 데이터 마이그레이션(기존 엑셀 → DB) — **선행 작업**
2. 로그인 / 사용자 관리
3. 거래처 목록 · 상세 화면
4. 신용평가 4개 항목 일자별 이력 저장 및 표시
5. 대시보드(정상/주의/위험 도넛 차트)
6. NICE BIZLINE 스크래핑 + Staging → DB 저장 흐름
7. 엑셀 내보내기(목록/상세 화면)

### 2차 개발 — OpenDART API

1. DART 기업 매칭(회사명 → corp_code → bizr_no 교차 검증)
2. 공시 목록 자동 수집(DS001)
3. 주요사항보고서 36종 수집(DS005)
4. 감사의견 체크(DS002)
5. DART 공시 화면(거래처 상세 내 탭)
6. 위험 공시 알림

### 3차 개발 — 국세청·KIND·고도화

1. 국세청 휴폐업 API 연동
2. KIND 시장조치 스크래핑
3. Rule 관리 화면
4. 변경 알림 기능(대표자·주소·전화번호 등 변경 감지)
5. Supabase RLS 정책 정교화 및 운영 감사 로그 보강

---

## 6. 화면 구성

> 실제 구현 시 위치·레이아웃은 화면을 보면서 조정합니다.  
> 각 화면 하단 **DB 연관** 항목은 해당 화면이 주로 사용하는 테이블·필드를 표시합니다.

### 공통 레이아웃

- **상단 헤더**: 로고, 마지막 수집일시, 위험 알림 카운트 아이콘(클릭 시 드롭다운), 사용자명/로그아웃
- **왼쪽 사이드바**: 대시보드 / 거래처 목록 / 관리자
- **메인 콘텐츠**: 사이드바 선택에 따른 화면
- **권한 처리**: `admin`은 관리자·DB 저장·Rule 관리 가능, `user`는 조회 중심 권한

### 6.1 로그인 `[1차]`

- 화면 중앙 카드 레이아웃
- 이메일 + 비밀번호 입력, 엔터키 지원, 실패 시 에러 메시지
- 관리자가 사전 등록한 활성 계정만 접속 가능
- 최초 로그인 시 비밀번호 변경 안내

> **DB 연관**: `users`(`email`, `role`, `is_active`) / Supabase Auth 사용 시 `auth.users` 연계 방식 검토

### 6.2 대시보드 `[1차 기본 / 2차 DART / 3차 국세청·KIND]`

**상단 — 요약 카드**

| 카드 | 내용 |
|---|---|
| 🔴 위험 N건 | `current_risk_level = '위험'` 거래처 수. 클릭 시 목록 이동 |
| 🟡 주의 N건 | `current_risk_level = '주의'` 거래처 수. 클릭 시 목록 이동 |
| 🟢 정상 N건 | `current_risk_level = '정상'` 거래처 수 |
| 전체 N건 | `current_status = '현재 관리 중'` 거래처 수 |

**중단 — 차트 + 수집 현황**

- 왼쪽: 리스크 등급 분포 도넛 차트(위험/주의/정상 비중)
- 오른쪽: 이번 주 수집 현황 체크리스트
  - NICE BIZLINE 완료 일시
  - 국세청 휴폐업 완료 일시
  - DART 공시 완료 일시 또는 2차 활성화 전 상태
  - **[데이터 가져오기 ▼]** 버튼 — 클릭 시 수집 항목 선택 드롭다운

**하단 — 최신 알림(주의/위험만, 최신 5건)**

| 항목 | 내용 |
|---|---|
| 등급 배지 | 🔴/🟡 |
| 날짜 | `detected_at`, `disclosure_date`, `event_date`, `checked_at` 중 이벤트 기준일 |
| 거래처명 | 클릭 시 해당 거래처 상세 이동 |
| 내용 | 대표자 변경 / 주소 변경 / 전화번호 변경 / DART 공시 제목 / 폐업 감지 / KIND 시장조치 |

> **DB 연관**: `customers` 집계 / `change_alerts` 미확인 최신순 / `dart_disclosures` 위험·주의 최신순 / `kind_market_events` 위험·주의 최신순 / `data_import_logs` 수집 완료 여부

### 6.3 거래처 목록 `[1차]`

**상단 — 검색·필터 바**

- 검색창: 거래처명 / 사업자번호 / 거래처코드 통합 검색
- 그룹 필터: 전체 / 외상매출금 / 대리점·지정점 / A/S 미수금 / 어음 등 DB 그룹 기반 동적 표시
- 등급 필터: 전체 / 위험 / 주의 / 정상
- 관리상태 필터: 현재 관리 중 / 과거 관리 대상 / 전체
- 엑셀 내보내기 버튼

**테이블 컬럼**

| 컬럼 | 내용 | 비고 |
|---|---|---|
| 등급 | 🔴/🟡/🟢 배지 | `current_risk_level` |
| 거래처명 | 이름 + 배지 | ⚠️변경감지 / 🆕신규발생 |
| 사업자번호 | 하이픈 없는 `biz_no` 표시 또는 UI에서 하이픈 포맷팅 | DB 저장은 10자리 숫자 |
| 거래처코드 | `customer_code` | |
| 그룹 | 소속 그룹명 | 다중 그룹 가능 |
| 기업평가 | 최신 등급 + 방향 화살표(↑↓→) | `last_evaluation_grade`, `grade_trend` 캐시 우선 사용 |
| 최종수집 | `last_collected_date` | 목록 성능을 위해 캐시 사용 |
| 관리상태 | 현재/과거 | `current_status` |

- 기본 정렬: 위험 → 주의 → 정상, 같은 등급 내 최신수집 순
- 위험/주의 행: 배경색 연하게 강조
- 행 클릭 → 거래처 상세 이동

> **DB 연관**: `customers` / `customer_group_members` / `customer_groups` / `change_alerts`

### 6.4 거래처 상세 `[1차 기본+NICE / 2차 DART / 3차 KIND+국세청]`

**상단 — 2단 카드**

| 왼쪽: 기본정보 | 오른쪽: 현재 리스크 종합 |
|---|---|
| 거래처명, 사업자번호, 거래처코드 | 최종 등급 배지(🔴/🟡/🟢 크게) |
| 대표자명(변경 시 이전값→현재값 표시 + ⚠️배지) | 위험 사유 요약(NICE·DART·KIND·국세청 별로) |
| 주소·전화번호(변경 시 동일하게 표시) | 최근 `risk_evaluations.reason_summary` |
| 개업일 / 폐업일(폐업 시 빨간색 강조) | [데이터 가져오기] [엑셀 내보내기] |
| 표준산업분류, 종업원수 | |

**탭 1: NICE 신용평가** `[1차]`

- 4개 항목 현재값 카드(기업평가 / WATCH / 현금흐름 / 연체정보)
- 연체정보: 있음(🔴) / 없음(🟢) / 미수집(Type B, 회색)
- 주간 추이 꺾은선 그래프
  - x축: 수집일(주 단위)
  - y축: `grade_mappings.score_value`
  - Rule 기준선 표시(주의/위험 임계값 수평 점선)

**탭 2: DART 공시** `[2차]`

- 주의/위험 등급만 표시(정상 숨김), 최신순 정렬
- 컬럼: 날짜 / 등급배지 / 공시 제목 / 제출인명(`flr_nm`) / 공시유형(`pblntf_ty`) / 판단 근거(`risk_reason`)
- 공시 없음 시: “위험·주의 공시 없음” 표시

**탭 3: KIND · 국세청** `[3차]`

- KIND 시장조치: `event_type` / `event_title` / `event_date` / 등급배지
- 국세청 상태: `business_status` / `checked_at` / `closing_date`
- 해당 없음 시 “해당 없음” 표시

**탭 4: 변경이력** `[1차]`

- `change_alerts` 목록: 날짜 / 항목(대표자·주소·전화번호 등) / 변경 전 → 변경 후 / 확인상태
- 미확인 항목: 강조 표시 + [확인] 버튼
- 확인 처리 시 `is_confirmed = true`, `confirmed_at`, `confirmed_by` 기록

### 6.5 Staging 검토 화면 `[1차]`

> NICE 스크래핑 완료 후 “DB에 저장” 전 관리자 검토 화면입니다.

**상단 — 수집 결과 요약 바**

- “스크래핑 완료 — YYYY-MM-DD HH:mm”
- 🆕 신규발생 N건(폐업확인 K건) | 기존고객 M건 | 실패 F건
- DART 매칭 진행 상태: 처리 중 / 완료 / 수동 검토 필요

**중단 — 검토 그리드**

- **신규발생 섹션**
  - 거래처명 / 사업자번호 / 국세청 상태(✅계속 / 🟡휴업 / 🔴폐업) / DART 매칭 상태
  - 폐업 거래처는 빨간색으로 경고 강조
- **기존고객 섹션**
  - 거래처명 / 변경된 필드(등급·대표자·주소·전화번호 등 `diff_data` 표시)
  - 변경 없는 기존고객은 기본 접힘 처리
- **실패/스킵 섹션**
  - `status='failed'` 또는 `skipped` row와 실패 사유 표시

**하단 — 고정 액션 바**

- [취소] [선택 스킵] [DB에 저장 ✅]
- 저장 성공 row는 `status='applied'`, `applied_at` 기록

> **DB 연관**: `nice_scraping_staging`(`session_id`, `is_new_customer`, `diff_data`, `status`, `applied_at`) / `customers`(`biz_no`) / `business_status_checks` / `dart_companies`

### 6.6 관리자 페이지 `[1차 기본 / 2차 DART매칭 / 3차 Rule관리]`

**탭 1: 사용자 관리** `[1차]`
- 목록: 이름 / 이메일 / 권한(`admin`·`user`) / 활성여부
- 버튼: [비밀번호 초기화] [비활성화] [신규 사용자 추가]

**탭 2: 수집 로그** `[1차]`
- 날짜 필터 + 유형 필터(`NICE | DART | KIND | BUSINESS_STATUS | ALL`)
- 컬럼: 날짜 / 유형 / 상태(`running | success | failed | partial`) / 전체·성공·실패 건수 / 소요시간
- 실패/일부실패 행 클릭 → 에러 메시지 상세 확인

**탭 3: DART 매칭 검토** `[2차]`
- `matched_by='review_required'` 상태 거래처 목록
- 컬럼: 거래처명 / 사업자번호 / DART 후보군 드롭다운(`candidates`) / [확정] [no_match 처리]
- no_match 처리 시 `corp_code=NULL`, `matched_by='no_match'` 저장

**탭 4: 그룹 관리** `[1차]`
- 목록: 그룹명 / 설명 / 정렬순서 / 활성여부
- [수정] [순서 변경] [그룹 추가]

**탭 5: Rule 관리** `[3차]`
- `risk_rules` 테이블 관리(`source_type`, `condition_type`, `condition_value`, `risk_level`, 활성여부)
- `grade_mappings` 테이블 관리(NICE 등급 텍스트 → 0~100 점수 매핑, 그래프 기준선 설정)
- [수정] [추가] [비활성화]

> **DB 연관**: `users` / `data_import_logs` / `dart_companies` / `customer_groups` / `risk_rules` / `grade_mappings`

---

## 7. 주요 기능 정의

### 7.1 데이터 가져오기(NICE)

1. 버튼 클릭 → `data_import_logs.status='running'`으로 백그라운드 Job 시작
2. Playwright로 NICE BIZLINE 로그인 → 그룹별 거래처 순회
3. 수집 결과 → `nice_scraping_staging`에 row-by-row 저장
4. 완료 후 `diff_data`, `is_new_customer` 계산 및 결과 요약 표시
5. 관리자 저장 확인 → `customers`, `nice_credit_snapshots`, `customer_group_members` upsert
6. 캐시 필드(`last_collected_date`, `last_evaluation_grade`, `grade_trend`) 갱신
7. `risk_evaluations` 생성 및 `current_risk_level` 갱신
8. `data_import_logs` 마감 및 staging 상태 업데이트

### 7.2 OpenDART 매칭(2차)

> **핵심 제약**: DART `CORPCODE.xml`에는 `bizr_no`가 없고 사업자번호로 직접 `corp_code`를 찾는 API도 없습니다. 회사명 매칭 → `corp_code` 확보 → `bizr_no` 교차 검증 순서가 자동화 경로입니다.

**매칭 프로세스(4단계)**

```text
[1단계] CORPCODE.xml 다운로드(최초 1회, 이후 월 1회 갱신)
  → 기업 목록 로컬 캐싱
  → { normalized_corp_name: [candidate...] } 구조 구성

[2단계] 회사명 정규화(양쪽 모두 적용)
  → 법인격 제거: 주식회사, (주), ㈜, 유한회사, (유), 합자회사, (합),
                 합명회사, 재단법인, (재), 사단법인, (사), 의료법인, (의),
                 영농조합법인, (영)
  → 특수문자·공백 제거, 대소문자 통일
  → 지점/지사/영업소 표현 제거 후 재시도

[3단계] 이름 매칭(3레벨)
  Level 1 — 원문 이름 완전 일치
  Level 2 — 정규화 이름 완전 일치
  Level 3 — 포함 관계(고객명 ⊂ corp_name 또는 반대)
  후보 없음 또는 후보 과다 → review_required 또는 no_match 검토

[4단계] bizr_no 교차 검증(후보가 있을 때만)
  → 후보 corp_code로 DS001 company.json 호출
  → 응답 bizr_no vs customers.biz_no 비교(숫자만 비교)
  → 일치 → 확정 / 불일치·동명 후보 多 → review_required
```

**matched_by 값 정의**

| 값 | 의미 |
|---|---|
| `name_exact_biz_verified` | 이름 완전 일치 + `bizr_no` 검증 완료(가장 신뢰) |
| `name_normalized_biz_verified` | 정규화 이름 일치 + `bizr_no` 검증 완료 |
| `name_only` | 이름 매칭 후보 1개이나 `bizr_no` 미확인 |
| `manual_mapped` | 자동 매칭 실패 후 관리자가 수동 연결 |
| `no_match` | DART에 없음 또는 매칭 제외. `corp_code`는 NULL |
| `review_required` | 동명 후보 多 또는 이름 일치·`bizr_no` 불일치 → 수동 검토 필요 |

**API 호출 한도 주의**

- OpenDART 일일 한도는 운영 시점에 공식 문서에서 재확인합니다.
- 최초 전체 거래처 매칭은 야간 배치로 분산 처리합니다.
- 한 번 매칭된 `corp_code`는 `dart_companies`에 저장하고 재호출하지 않습니다.
- 신규 거래처와 `review_required` 대상만 매칭을 시도합니다.
- `company.json` 호출은 후보가 있는 건만 수행하고, `no_match` 건은 호출하지 않습니다.

### 7.3 알림 조건

- 대표자명, 주소, 전화번호, 거래처명, 개업일, 폐업일 변경 감지
- 신용평가 등급 기준값 초과(NICE)
- 위험·주의 공시 신규 등록(DART)
- 휴업/폐업, 거래정지, 관리종목, 상장폐지 확인
- `risk_evaluations.final_risk_level`이 이전보다 악화된 경우

### 7.4 거래처 그룹

- DB에서 동적으로 관리하며 고정값으로 하드코딩하지 않습니다.
- 향후 그룹 추가 가능: 견적 고객, 수주 고객 등
- 한 거래처가 여러 그룹에 동시 포함될 수 있습니다.
- 이번 주 수집 목록에서 제외된 거래처는 `current_status='과거 관리 대상'` 처리하되 삭제하지 않습니다.

---

## 8. 개발 시 필수 주의사항

1. **민감정보** — API 키·로그인 정보는 `.env`와 배포 Secret으로 관리하고 `.gitignore`에 포함합니다.
2. **거래처 삭제 금지** — 이력 보관을 우선하며 상태값으로 관리합니다.
3. **사업자번호 정규화** — 모든 입력 경로에서 하이픈·공백 제거 후 10자리 숫자 검증을 수행합니다.
4. **상태값 준수** — DB `CHECK` 제약과 동일한 enum만 UI/API에서 사용합니다.
5. **원본 응답 보관** — API/스크래핑 결과는 필요한 범위로 `raw_data jsonb`에 저장하고 민감정보는 마스킹합니다.
6. **스크래핑 모듈 분리** — `scraper/nice_bizline.py`, `scraper/kind.py` 등 별도 파일로 분리합니다.
7. **NICE BIZLINE 실행환경** — 로컬 Windows와 Render/Linux headless 환경을 모두 검증하고, 봇 탐지 리스크를 기록합니다.
8. **DB 변경 시** — `DB.md`와 `DESIGN.md` 변경 이력을 모두 업데이트합니다.
9. **RLS 적용** — 운영 전 Supabase RLS를 활성화하고 관리자/일반 사용자 권한을 분리합니다.
10. **updated_at 처리** — 앱에서 직접 갱신하기보다 DB의 `set_updated_at()` 트리거를 기본으로 사용합니다.

---

## 9. 개발 착수 순서(Claude + Gemini 협의)

| 단계 | 작업 | 목표 | 비고 |
|---|---|---|---|
| **1단계** | NICE BIZLINE 스크래핑 테스트 | 로그인·봇차단 회피·필드 추출 가능 여부 확인 | 시스템 최대 리스크 — 실패 시 설계 재검토 필요 |
| **2단계** | Supabase 세팅 + DB 스키마 생성 | `DB.md` 16개 테이블, 제약, 인덱스, 트리거 생성 및 연결 확인 | `pgcrypto`, `set_updated_at()`, RLS 기본 정책 검토 포함 |
| **3단계** | 기존 엑셀 데이터 마이그레이션 | 보유 중인 NICE 엑셀 → `customers`, `nice_credit_snapshots` 적재 | 실제 데이터로 개발·검증 가능 |
| **4단계** | MVP UI 개발 | 거래처 목록 → 거래처 상세 → 대시보드 순으로 핵심 화면 완성 | 캐시 필드 기반 목록 성능 검증 |
| **5단계** | DART / 국세청 API 연동 + 자동화 | 공시 수집, 기업 매칭, 휴폐업 조회, Staging 검토 프로세스 완성 | 기반이 갖춰진 후 고도화 |

### 단계별 상세

**1단계 — NICE 스크래핑 테스트**
- Playwright로 NICE BIZLINE 로그인 → 거래처 1건 데이터 추출 POC
- 기업평가 / WATCH / 현금흐름 / 연체정보 4개 항목 실제 등급값 확인
- `grade_mappings` 점수 매핑 확정, RULES.md 임계값 확정 가능
- 로컬 Windows와 Docker/Render headless 환경 봇 탐지 테스트 포함

**2단계 — Supabase 세팅**
- Supabase 프로젝트 생성, `DB.md` DDL 실행
- `CREATE EXTENSION IF NOT EXISTS pgcrypto;` 및 `set_updated_at()` 트리거 확인
- `.env` 환경변수 설정(API URL, anon key, service key)
- RLS 정책 초안 작성 및 기본 연결 테스트

**3단계 — 기존 엑셀 마이그레이션**
- 보유 NICE 엑셀 파일 → Python 스크립트로 일괄 적재
- `biz_no` 정규화·중복 체크·오류 row 리포트 생성
- `customers` 초기 등록 + `nice_credit_snapshots` 과거 이력 적재
- `excel_upload_logs` 처리 결과 확인

**4단계 — MVP UI**
- Next.js + Supabase 클라이언트 세팅
- 거래처 목록(필터·검색·리스크 배지·캐시 필드 사용)
- 거래처 상세(기본정보 + NICE 4개 추이 그래프)
- 대시보드(요약 카드 + 분포 차트 + 최신 알림)

**5단계 — API 연동 및 자동화**
- OpenDART DS001 / DS005 / DS002 공시 수집
- CORPCODE.xml 기반 기업 매칭(`dart_companies`)
- 국세청 휴폐업 API 연동
- Staging 검토 화면 연동(`nice_scraping_staging` → DB 반영)
- Rule 기반 `risk_evaluations` 생성 자동화

---

## 변경 이력

| 일자 | 내용 | 작성자 |
|---|---|---|
| 2026-05-14 | 최초 작성 | Hongsang Lee |
| 2026-05-15 | 데이터 수집 방식 변경(엑셀 중간 단계 제거 → 서버 스크래핑 + Staging → DB 직접 저장), 개발 순서 재조정(1차 NICE, 2차 DART, 3차 국세청·KIND), 초기 데이터 마이그레이션 섹션 추가, Playwright 전환 명시, 스크래퍼 경량화 방향(TypeA/B 통합 파서, row-by-row staging 저장) 추가, DART 매칭 상세 스펙 추가(4단계 프로세스, matched_by 값 정의, API 한도 주의사항, 수동매칭 UI) | Hongsang Lee |
| 2026-05-15 | 3가지 데이터 수집 운영 방법 확정 및 상세화 — NICE: 신규발생/기존고객 2분류·Staging 검토 후 DB저장·DART 매칭 백그라운드 연계 / DART: B-1 매칭작업·B-2 공시수집 구분·DS005 36종 전체수집·공시 제목+링크+risk_reason 저장 / 국세청: 신규발생 즉시조회+주 1회 정기(NICE와 통합)·폐업일자 기본정보 표시. 특정 거래처 선택 수집 기능 추가 | Hongsang Lee |
| 2026-05-15 | Section 6 화면 구성 전면 상세화 — 공통 레이아웃, 6.1~6.6 각 화면별 표시 항목·UI 컴포넌트·인터랙션·개발 차수 정의. Staging 검토 화면(6.5) 신규 추가, 관리자 페이지(6.6) 5개 탭 구조 확정 | Hongsang Lee |
| 2026-05-15 | DB 교차 검토 반영 — 각 화면에 DB 연관 테이블·필드 설명 추가, 관리자 페이지 Rule 관리 탭에 grade_mappings 관리 기능 추가 | Hongsang Lee |
| 2026-05-15 | Section 9 개발 착수 순서 추가 — Claude+Gemini 협의, 5단계(스크래핑 테스트→Supabase 세팅→엑셀 마이그레이션→MVP UI→API 연동) | Claude + Gemini |
| 2026-05-18 | `DB.md` 보강사항 반영 — 중복 문서 제거, 사업자번호 정규화, Staging·로그 상태값, DART no_match/corp_code nullable, 캐시 갱신, RLS·raw_data 마스킹·updated_at 트리거 운영 원칙 추가 | Codex |
