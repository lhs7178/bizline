-- OpenDART/KIND 수집 테스트에 필요한 최소 Supabase PostgreSQL 스키마입니다.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE customers (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  biz_no        text UNIQUE NOT NULL,
  customer_name text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_customers_biz_no_format CHECK (biz_no ~ '^[0-9]{10}$'),
  CONSTRAINT chk_customers_name_not_blank CHECK (btrim(customer_name) <> '')
);

CREATE TRIGGER trg_customers_updated_at
BEFORE UPDATE ON customers
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE dart_companies (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  corp_code   text,
  corp_name   text,
  bizr_no     text,
  stock_code  text,
  corp_cls    text,
  market_type text,
  matched_by  text,
  matched_at  timestamptz DEFAULT now(),
  candidates  jsonb,
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

CREATE TRIGGER trg_dart_companies_updated_at
BEFORE UPDATE ON dart_companies
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE dart_disclosures (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  customer_id      uuid NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  corp_code        text NOT NULL,
  receipt_no       text UNIQUE NOT NULL,
  report_name      text,
  flr_nm           text,
  pblntf_ty        text,
  disclosure_date  date,
  dart_url         text,
  risk_level       text NOT NULL DEFAULT '정상',
  risk_reason      text,
  raw_data         jsonb,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT chk_dart_disclosures_receipt_not_blank CHECK (btrim(receipt_no) <> ''),
  CONSTRAINT chk_dart_disclosures_risk_level CHECK (risk_level IN ('정상', '주의', '위험'))
);

CREATE INDEX idx_dart_disc_customer
  ON dart_disclosures(customer_id);
CREATE INDEX idx_dart_disc_customer_date
  ON dart_disclosures(customer_id, disclosure_date DESC);
CREATE INDEX idx_dart_disc_corp_date
  ON dart_disclosures(corp_code, disclosure_date DESC);

CREATE TRIGGER trg_dart_disclosures_updated_at
BEFORE UPDATE ON dart_disclosures
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

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
