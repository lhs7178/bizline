# RiskManagement DB 구성

> DB: Supabase PostgreSQL  
> DB 구조 변경 시 하단 변경 이력에 반드시 기록합니다.

---

## 보완 요약

- 원문에 중복으로 포함되어 있던 `DB.md` 전체 반복 내용을 제거했습니다.
- Supabase PostgreSQL에서 UUID 기본값을 안정적으로 사용하기 위한 `pgcrypto` 확장 선언을 추가했습니다.
- 코드값 컬럼에는 `CHECK` 제약을 추가해 잘못된 상태값 유입을 방지했습니다.
- 자식 테이블에는 적절한 `ON DELETE CASCADE` 또는 `ON DELETE SET NULL` 정책을 명시했습니다.
- `updated_at` 자동 갱신 트리거를 공통 함수로 추가했습니다.
- 목록/상세/최신 이력 조회에 필요한 복합 인덱스와 중복 방지 제약을 보강했습니다.
- 수집 로그, 업로드 로그, staging 데이터에 음수 카운트와 잘못된 상태값이 들어가지 않도록 제약을 추가했습니다.

---

## 적용 전 공통 설정

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

> `updated_at` 컬럼이 있는 테이블은 각 테이블 생성 후 `set_updated_at()` 트리거를 생성합니다.

---

## 테이블 목록

| # | 테이블 | 설명 |
|---|---|---|
| 1 | users | 사용자 계정 |
| 2 | customer_groups | 거래처 그룹 |
| 3 | customers | 거래처 기본정보 + 최신값 캐시 |
| 4 | customer_group_members | 거래처-그룹 매핑 |
| 5 | nice_credit_snapshots | 신용평가 일자별 이력 |
| 6 | nice_scraping_staging | NICE 스크래핑 임시 저장(DB 반영 전 검토용) |
| 7 | dart_companies | OpenDART 매칭 정보 |
| 8 | dart_disclosures | OpenDART 공시자료 |
| 9 | kind_market_events | KIND 시장조치 |
| 10 | business_status_checks | 국세청 휴폐업 |
| 11 | risk_rules | 리스크 Rule |
| 12 | risk_evaluations | 거래처별 평가 결과 |
| 13 | change_alerts | 변경 알림 이력 |
| 14 | data_import_logs | 수집 실행 이력 |
| 15 | excel_upload_logs | 엑셀 업로드 이력(초기 데이터 마이그레이션용) |
| 16 | grade_mappings | NICE 등급 텍스트 → 그래프 점수 변환 매핑 |

---

## 테이블 정의

### users

```sql
CREATE TABLE users (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email      text UNIQUE NOT NULL,
  name       text NOT NULL,
  role       text NOT NULL DEFAULT 'user',
  is_active  boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_users_role CHECK (role IN ('admin', 'user')),
  CONSTRAINT chk_users_email_not_blank CHECK (btrim(email) <> ''),
  CONSTRAINT chk_users_name_not_blank CHECK (btrim(name) <> '')
);

CREATE TRIGGER trg_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

> Supabase Auth를 사용하는 경우에는 `public.users.id`를 `auth.users.id`와 동일하게 맞추거나 별도 `auth_user_id uuid UNIQUE` 컬럼을 두는 방식을 검토합니다.

---

### customer_groups

```sql
CREATE TABLE customer_groups (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  group_name  text NOT NULL,
  description text,
  sort_order  integer NOT NULL DEFAULT 0,
  is_active   boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_customer_groups_group_name UNIQUE (group_name),
  CONSTRAINT chk_customer_groups_name_not_blank CHECK (btrim(group_name) <> ''),
  CONSTRAINT chk_customer_groups_sort_order CHECK (sort_order >= 0)
);

CREATE INDEX idx_customer_groups_active_sort
  ON customer_groups(is_active, sort_order, group_name);

CREATE TRIGGER trg_customer_groups_updated_at
BEFORE UPDATE ON customer_groups
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

```sql
-- 초기 데이터 예시
INSERT INTO customer_groups (group_name, sort_order)
VALUES
  ('외상매출금', 10),
  ('대리점·지정점', 20),
  ('A/S 미수금', 30),
  ('어음·출하후 세금계산서 미발행', 40)
ON CONFLICT (group_name) DO NOTHING;
```

---

### customers

```sql
CREATE TABLE customers (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  biz_no                text UNIQUE NOT NULL,       -- 사업자등록번호(핵심 매칭 키, 숫자 10자리 권장)
  customer_name         text NOT NULL,
  customer_code         text,
  ceo_name              text,
  address               text,
  phone                 text,
  opening_date          date,
  closing_date          date,                       -- 국세청 API 연동
  industry_code_name    text,
  main_product          text,
  employee_count        integer,
  current_risk_level    text NOT NULL DEFAULT '정상',
  current_status        text NOT NULL DEFAULT '현재 관리 중',
  last_collected_date   date,                       -- 최종 수집일 캐시(거래처 목록 성능용)
  last_evaluation_grade text,                       -- 최신 기업평가 등급 캐시(거래처 목록 표시용)
  grade_trend           text NOT NULL DEFAULT 'stable',
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_customers_biz_no_format CHECK (biz_no ~ '^[0-9]{10}$'),
  CONSTRAINT chk_customers_name_not_blank CHECK (btrim(customer_name) <> ''),
  CONSTRAINT chk_customers_employee_count CHECK (employee_count IS NULL OR employee_count >= 0),
  CONSTRAINT chk_customers_risk_level CHECK (current_risk_level IN ('정상', '주의', '위험')),
  CONSTRAINT chk_customers_status CHECK (current_status IN ('현재 관리 중', '과거 관리 대상')),
  CONSTRAINT chk_customers_grade_trend CHECK (grade_trend IN ('up', 'down', 'stable')),
  CONSTRAINT chk_customers_dates CHECK (closing_date IS NULL OR opening_date IS NULL OR closing_date >= opening_date)
);

CREATE INDEX idx_customers_biz_no
  ON customers(biz_no);
CREATE INDEX idx_customers_status
  ON customers(current_status);
CREATE INDEX idx_customers_risk_level
  ON customers(current_risk_level);
CREATE INDEX idx_customers_name
  ON customers(customer_name);
CREATE INDEX idx_customers_status_risk_name
  ON customers(current_status, current_risk_level, customer_name);

CREATE TRIGGER trg_customers_updated_at
BEFORE UPDATE ON customers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

> `last_collected_date`, `last_evaluation_grade`, `grade_trend`는 NICE 수집 데이터를 승인/저장할 때 함께 갱신합니다.  
> `biz_no`는 하이픈 없는 10자리 숫자로 정규화해 저장하는 것을 권장합니다.

---

### customer_group_members

```sql
CREATE TABLE customer_group_members (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id   uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  group_id      uuid NOT NULL REFERENCES customer_groups(id) ON DELETE CASCADE,
  is_active     boolean NOT NULL DEFAULT true,
  first_seen_at timestamptz,
  last_seen_at  timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_customer_group_members UNIQUE (customer_id, group_id),
  CONSTRAINT chk_customer_group_members_seen_dates CHECK (last_seen_at IS NULL OR first_seen_at IS NULL OR last_seen_at >= first_seen_at)
);

CREATE INDEX idx_customer_group_members_customer
  ON customer_group_members(customer_id, is_active);
CREATE INDEX idx_customer_group_members_group
  ON customer_group_members(group_id, is_active);

CREATE TRIGGER trg_customer_group_members_updated_at
BEFORE UPDATE ON customer_group_members
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

### nice_credit_snapshots

```sql
-- 기업평가·WATCH·현금흐름·연체정보 — 매주 수집 시 날짜별 이력 저장
CREATE TABLE nice_credit_snapshots (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id       uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  collected_date    date NOT NULL,           -- 수집 기준일(주 단위)
  collected_at      timestamptz NOT NULL DEFAULT now(),
  evaluation_grade  text,                    -- 기업평가(텍스트 등급, grade_mappings로 점수 변환)
  watch_status      text,                    -- WATCH
  cash_flow_status  text,                    -- 현금흐름
  overdue_status    text,                    -- 연체정보(Type B SOHO는 NULL 가능)
  raw_data          jsonb,
  created_at        timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_nice_credit_snapshots_customer_date UNIQUE (customer_id, collected_date)
);

CREATE INDEX idx_nice_customer
  ON nice_credit_snapshots(customer_id);
CREATE INDEX idx_nice_date
  ON nice_credit_snapshots(collected_date);
CREATE INDEX idx_nice_customer_date
  ON nice_credit_snapshots(customer_id, collected_date DESC);
```

---

### nice_scraping_staging

```sql
-- NICE 스크래핑 완료 후 DB 반영 전 임시 저장 영역
-- 스크래핑 실패/중단 시 데이터 유실 방지. 사용자 확인 후 본 테이블로 이전.
CREATE TABLE nice_scraping_staging (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id       uuid NOT NULL,             -- 스크래핑 세션 단위 묶음
  biz_no           text NOT NULL,
  customer_name    text,
  customer_code    text,
  ceo_name         text,
  address          text,
  phone            text,
  opening_date     text,                      -- 원본값 보존 후 승인 시 date 변환
  industry_code    text,
  employee_count   text,                      -- 원본값 보존 후 승인 시 integer 변환
  evaluation_grade text,                      -- 기업평가
  watch_status     text,                      -- WATCH
  cash_flow_status text,                      -- 현금흐름
  overdue_status   text,                      -- 연체정보
  group_name       text,                      -- 원본 그룹명(예: 91.외상매출금)
  scraped_at       timestamptz NOT NULL DEFAULT now(),
  status           text NOT NULL DEFAULT 'pending',
  applied_at       timestamptz,
  is_new_customer  boolean NOT NULL DEFAULT false,
  diff_data        jsonb,                     -- 예: {"ceo_name": {"old": "홍길동", "new": "김철수"}}

  CONSTRAINT chk_staging_biz_no_format CHECK (biz_no ~ '^[0-9]{10}$'),
  CONSTRAINT chk_staging_status CHECK (status IN ('pending', 'applied', 'skipped', 'failed')),
  CONSTRAINT chk_staging_applied_at CHECK ((status = 'applied' AND applied_at IS NOT NULL) OR status <> 'applied')
);

CREATE INDEX idx_staging_session
  ON nice_scraping_staging(session_id);
CREATE INDEX idx_staging_biz_no
  ON nice_scraping_staging(biz_no);
CREATE INDEX idx_staging_session_status
  ON nice_scraping_staging(session_id, status, scraped_at DESC);
```

---

### dart_companies

```sql
CREATE TABLE dart_companies (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  corp_code   text,            -- DART 고유번호(매칭없음/no_match 상태에서는 NULL 가능)
  corp_name   text,
  bizr_no     text,            -- DART 기업개황에서 확인한 사업자번호(customers.biz_no 교차 검증용)
  stock_code  text,            -- 종목코드
  corp_cls    text,            -- Y=유가증권 | K=코스닥 | N=코넥스 | E=기타법인
  market_type text,            -- 유가증권 | 코스닥 | 코넥스 | 기타법인 | 비상장 | 매칭없음
  matched_by  text,            -- name_exact_biz_verified | name_normalized_biz_verified | name_only | manual_mapped | no_match | review_required
  matched_at  timestamptz,
  candidates  jsonb,           -- 자동 매칭 실패 시 DART 후보 리스트 임시 보관(관리자 수동 매칭 화면용)
  raw_data    jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_dart_companies_customer UNIQUE (customer_id),
  CONSTRAINT chk_dart_companies_bizr_no_format CHECK (bizr_no IS NULL OR bizr_no ~ '^[0-9]{10}$'),
  CONSTRAINT chk_dart_companies_corp_cls CHECK (corp_cls IS NULL OR corp_cls IN ('Y', 'K', 'N', 'E')),
  CONSTRAINT chk_dart_companies_market_type CHECK (market_type IS NULL OR market_type IN ('유가증권', '코스닥', '코넥스', '기타법인', '비상장', '매칭없음')),
  CONSTRAINT chk_dart_companies_matched_by CHECK (matched_by IS NULL OR matched_by IN ('name_exact_biz_verified', 'name_normalized_biz_verified', 'name_only', 'manual_mapped', 'no_match', 'review_required'))
);

CREATE UNIQUE INDEX uq_dart_companies_corp_code
  ON dart_companies(corp_code) WHERE corp_code IS NOT NULL;
CREATE INDEX idx_dart_companies_customer
  ON dart_companies(customer_id);
CREATE INDEX idx_dart_companies_stock_code
  ON dart_companies(stock_code) WHERE stock_code IS NOT NULL;
CREATE INDEX idx_dart_companies_bizr_no
  ON dart_companies(bizr_no) WHERE bizr_no IS NOT NULL;
CREATE INDEX idx_dart_companies_match_status
  ON dart_companies(matched_by, matched_at DESC);

CREATE TRIGGER trg_dart_companies_updated_at
BEFORE UPDATE ON dart_companies
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

> DART 매칭 전략: `CORPCODE.xml(corp_name 기준)` → 기업개황 `bizr_no` 확인 → `customers.biz_no` 교차 검증.

---

### dart_disclosures

```sql
CREATE TABLE dart_disclosures (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id      uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  corp_code        text NOT NULL,
  receipt_no       text UNIQUE NOT NULL,   -- 접수번호(중복 방지)
  report_name      text,
  flr_nm           text,                   -- 제출인명(공시 제출 주체, 거래처 상세 화면 표시용)
  pblntf_ty        text,                   -- 공시유형(정기공시·주요사항보고 등, 필터링용)
  disclosure_date  date,
  dart_url         text,
  risk_level       text NOT NULL DEFAULT '정상',
  risk_reason      text,                   -- 위험 판단 근거 키워드(클릭 전 사유 표시용)
  raw_data         jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_dart_disclosures_receipt_not_blank CHECK (btrim(receipt_no) <> ''),
  CONSTRAINT chk_dart_disclosures_risk_level CHECK (risk_level IN ('정상', '주의', '위험'))
);

CREATE INDEX idx_dart_disc_customer
  ON dart_disclosures(customer_id);
CREATE INDEX idx_dart_disc_risk
  ON dart_disclosures(risk_level);
CREATE INDEX idx_dart_disc_customer_date
  ON dart_disclosures(customer_id, disclosure_date DESC);
CREATE INDEX idx_dart_disc_corp_date
  ON dart_disclosures(corp_code, disclosure_date DESC);

CREATE TRIGGER trg_dart_disclosures_updated_at
BEFORE UPDATE ON dart_disclosures
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

### kind_market_events

```sql
CREATE TABLE kind_market_events (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  stock_code  text NOT NULL,
  event_type  text NOT NULL,
  event_title text,
  event_date  date,
  source_url  text,
  risk_level  text NOT NULL DEFAULT '주의',
  risk_reason text,
  raw_data    jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_kind_market_events_type CHECK (event_type IN ('관리종목', '거래정지', '실질심사', '상장폐지', '기타')),
  CONSTRAINT chk_kind_market_events_risk_level CHECK (risk_level IN ('정상', '주의', '위험')),
  CONSTRAINT uq_kind_market_events_unique_event UNIQUE (stock_code, event_type, event_date, event_title)
);

CREATE INDEX idx_kind_market_events_customer_date
  ON kind_market_events(customer_id, event_date DESC);
CREATE INDEX idx_kind_market_events_stock_date
  ON kind_market_events(stock_code, event_date DESC);
CREATE INDEX idx_kind_market_events_risk
  ON kind_market_events(risk_level);

CREATE TRIGGER trg_kind_market_events_updated_at
BEFORE UPDATE ON kind_market_events
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

### business_status_checks

```sql
CREATE TABLE business_status_checks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id     uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  biz_no          text NOT NULL,
  business_status text NOT NULL,   -- 계속사업자 | 휴업자 | 폐업자
  tax_type        text,
  closing_date    date,
  checked_at      timestamptz NOT NULL DEFAULT now(),
  raw_data        jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_business_status_biz_no_format CHECK (biz_no ~ '^[0-9]{10}$'),
  CONSTRAINT chk_business_status CHECK (business_status IN ('계속사업자', '휴업자', '폐업자'))
);

CREATE INDEX idx_business_status_customer_checked
  ON business_status_checks(customer_id, checked_at DESC);
CREATE INDEX idx_business_status_biz_no_checked
  ON business_status_checks(biz_no, checked_at DESC);
CREATE INDEX idx_business_status_status
  ON business_status_checks(business_status);
```

---

### risk_rules

```sql
CREATE TABLE risk_rules (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  rule_name       text NOT NULL,
  source_type     text NOT NULL,
  condition_type  text NOT NULL,
  condition_value text,
  risk_level      text NOT NULL,
  description     text,
  is_active       boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_risk_rules_name_not_blank CHECK (btrim(rule_name) <> ''),
  CONSTRAINT chk_risk_rules_source_type CHECK (source_type IN ('NICE', 'DART', 'KIND', 'BUSINESS_STATUS')),
  CONSTRAINT chk_risk_rules_risk_level CHECK (risk_level IN ('주의', '위험'))
);

CREATE INDEX idx_risk_rules_active_source
  ON risk_rules(is_active, source_type);

CREATE TRIGGER trg_risk_rules_updated_at
BEFORE UPDATE ON risk_rules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

---

### risk_evaluations

```sql
CREATE TABLE risk_evaluations (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id      uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  evaluated_at     timestamptz NOT NULL DEFAULT now(),
  final_risk_level text NOT NULL,
  reason_summary   text,
  detail           jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_risk_evaluations_final_level CHECK (final_risk_level IN ('정상', '주의', '위험'))
);

CREATE INDEX idx_risk_evaluations_customer_evaluated
  ON risk_evaluations(customer_id, evaluated_at DESC);
CREATE INDEX idx_risk_evaluations_final_level
  ON risk_evaluations(final_risk_level);
```

---

### change_alerts

```sql
CREATE TABLE change_alerts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id  uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  field_name   text NOT NULL,
  old_value    text,
  new_value    text,
  detected_at  timestamptz NOT NULL DEFAULT now(),
  is_confirmed boolean NOT NULL DEFAULT false,
  confirmed_at timestamptz,
  confirmed_by uuid REFERENCES users(id) ON DELETE SET NULL,

  CONSTRAINT chk_change_alerts_field_name CHECK (field_name IN ('ceo_name', 'address', 'phone', 'customer_name', 'opening_date', 'closing_date')),
  CONSTRAINT chk_change_alerts_confirmed CHECK (
    (is_confirmed = true AND confirmed_at IS NOT NULL)
    OR (is_confirmed = false)
  )
);

CREATE INDEX idx_change_alerts_customer_confirmed
  ON change_alerts(customer_id, is_confirmed);
CREATE INDEX idx_change_alerts_detected
  ON change_alerts(detected_at DESC);
```

---

### data_import_logs

```sql
CREATE TABLE data_import_logs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  import_type   text NOT NULL,
  started_at    timestamptz,
  finished_at   timestamptz,
  status        text NOT NULL DEFAULT 'running',
  total_count   integer NOT NULL DEFAULT 0,
  success_count integer NOT NULL DEFAULT 0,
  failed_count  integer NOT NULL DEFAULT 0,
  error_message text,
  created_by    uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_data_import_logs_type CHECK (import_type IN ('NICE', 'DART', 'KIND', 'BUSINESS_STATUS', 'ALL')),
  CONSTRAINT chk_data_import_logs_status CHECK (status IN ('running', 'success', 'failed', 'partial')),
  CONSTRAINT chk_data_import_logs_counts CHECK (total_count >= 0 AND success_count >= 0 AND failed_count >= 0),
  CONSTRAINT chk_data_import_logs_finished_at CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX idx_data_import_logs_type_created
  ON data_import_logs(import_type, created_at DESC);
CREATE INDEX idx_data_import_logs_status_created
  ON data_import_logs(status, created_at DESC);
```

---

### grade_mappings

```sql
-- NICE 텍스트 등급 → 그래프 점수 변환 매핑 테이블
-- 실제 NICE 데이터 수집 후 등급값 확인하여 초기 데이터 입력
CREATE TABLE grade_mappings (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type  text NOT NULL,
  grade_text   text NOT NULL,
  score_value  integer NOT NULL, -- 그래프 y축 점수(높을수록 좋음, 예: AAA=100, AA=90 ... D=10)
  risk_level   text,
  created_at   timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_grade_mappings_source_grade UNIQUE(source_type, grade_text),
  CONSTRAINT chk_grade_mappings_source_type CHECK (source_type IN ('NICE_EVAL', 'NICE_WATCH', 'NICE_CASH', 'NICE_OVERDUE')),
  CONSTRAINT chk_grade_mappings_grade_not_blank CHECK (btrim(grade_text) <> ''),
  CONSTRAINT chk_grade_mappings_score CHECK (score_value BETWEEN 0 AND 100),
  CONSTRAINT chk_grade_mappings_risk_level CHECK (risk_level IS NULL OR risk_level IN ('정상', '주의', '위험'))
);

CREATE INDEX idx_grade_mappings_source_score
  ON grade_mappings(source_type, score_value DESC);
```

---

### excel_upload_logs

```sql
CREATE TABLE excel_upload_logs (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_name      text NOT NULL,
  uploaded_by    uuid REFERENCES users(id) ON DELETE SET NULL,
  uploaded_at    timestamptz NOT NULL DEFAULT now(),
  upload_date    date,
  total_rows     integer NOT NULL DEFAULT 0,
  inserted_count integer NOT NULL DEFAULT 0,
  updated_count  integer NOT NULL DEFAULT 0,
  skipped_count  integer NOT NULL DEFAULT 0,
  error_count    integer NOT NULL DEFAULT 0,
  status         text NOT NULL DEFAULT 'pending',
  error_message  text,

  CONSTRAINT chk_excel_upload_logs_file_not_blank CHECK (btrim(file_name) <> ''),
  CONSTRAINT chk_excel_upload_logs_counts CHECK (
    total_rows >= 0
    AND inserted_count >= 0
    AND updated_count >= 0
    AND skipped_count >= 0
    AND error_count >= 0
  ),
  CONSTRAINT chk_excel_upload_logs_status CHECK (status IN ('pending', 'success', 'failed', 'partial'))
);

CREATE INDEX idx_excel_upload_logs_uploaded_at
  ON excel_upload_logs(uploaded_at DESC);
CREATE INDEX idx_excel_upload_logs_status
  ON excel_upload_logs(status);
```

---

## 테이블 관계 요약

```text
customers  (last_collected_date·last_evaluation_grade·grade_trend 캐시 필드 포함)
  ├── customer_group_members → customer_groups
  ├── nice_credit_snapshots           (UNIQUE: customer_id + collected_date)
  ├── dart_companies                  (bizr_no로 customers.biz_no 교차 검증, candidates JSONB로 후보 보관)
  ├── dart_disclosures                (flr_nm 제출인명 포함)
  ├── kind_market_events
  ├── business_status_checks
  ├── risk_evaluations
  └── change_alerts                   (INDEX: customer_id + is_confirmed)

nice_scraping_staging                 (is_new_customer·diff_data 포함 → 승인 후 customers/nice_credit_snapshots로 이전)

grade_mappings                        (NICE 등급 텍스트 → 점수 변환, 그래프 y축 및 기준선 표시용)

users
  ├── data_import_logs
  ├── excel_upload_logs
  └── change_alerts (confirmed_by)
```

---

## 운영 권장 사항

1. **사업자등록번호 정규화**: DB 저장 전 하이픈과 공백을 제거하고 10자리 숫자로 저장합니다.
2. **수집 데이터 승인 흐름**: NICE 스크래핑 결과는 먼저 `nice_scraping_staging`에 저장하고, 승인 시 `customers`, `customer_group_members`, `nice_credit_snapshots`에 upsert합니다.
3. **최신값 캐시 갱신**: `nice_credit_snapshots` 저장 후 `customers.last_collected_date`, `customers.last_evaluation_grade`, `customers.grade_trend`를 같은 트랜잭션에서 갱신합니다.
4. **리스크 재평가**: NICE/DART/KIND/국세청 데이터 수집 완료 후 `risk_rules` 기반으로 `risk_evaluations`를 생성하고 `customers.current_risk_level`을 갱신합니다.
5. **Row Level Security**: Supabase 운영 환경에서는 테이블별 RLS를 활성화하고 `admin`/`user` 권한별 조회·수정 정책을 별도로 정의합니다.
6. **대용량 원본 데이터**: `raw_data` JSONB는 감사/디버깅에 필요한 범위로만 저장하고, 민감정보가 포함될 경우 별도 마스킹 정책을 적용합니다.

---

## 변경 이력

| 일자 | 내용 | 작성자 |
|---|---|---|
| 2026-05-14 | 최초 작성(14개 테이블) | Hongsang Lee |
| 2026-05-15 | `nice_credit_snapshots` `UNIQUE(customer_id, collected_date)` 추가, `dart_companies.bizr_no` 필드 추가, `nice_scraping_staging` 테이블 추가(15개 테이블) | Hongsang Lee |
| 2026-05-15 | 화면 설계 교차 검토 반영 — `customers`에 `last_collected_date`·`last_evaluation_grade`·`grade_trend` 캐시 필드 추가 / `dart_disclosures`에 `flr_nm`·`pblntf_ty` 추가 / `nice_scraping_staging`에 `is_new_customer`·`diff_data` 추가 / `dart_companies`에 `candidates` 추가 / `grade_mappings` 신규 테이블 추가(#16) / `change_alerts`·`nice_credit_snapshots`·`dart_disclosures` 인덱스 보강(16개 테이블) | Hongsang Lee |
| 2026-05-18 | 중복 문서 제거, 공통 확장·트리거 추가, CHECK 제약·FK 삭제 정책·인덱스·운영 권장 사항 보강 | Codex |
