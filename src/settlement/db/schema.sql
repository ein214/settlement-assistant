-- 작가(정산 대상자). 연락처·계좌·주민/사업자번호 등 개인정보 컬럼은 두지 않는다.
CREATE TABLE IF NOT EXISTS providers (
    id            INTEGER PRIMARY KEY,
    provider_type TEXT NOT NULL,            -- author 등
    display_name  TEXT NOT NULL,            -- 가상 이름 (동명이인 가능)
    author_type   TEXT NOT NULL DEFAULT 'basic'
);

-- 정산 계약. 조건이 바뀌면 기존 행의 expired_at만 닫고 새 행을 추가한다 (행 = 비율 이력).
CREATE TABLE IF NOT EXISTS contracts (
    id                    INTEGER PRIMARY KEY,
    provider_id           INTEGER NOT NULL REFERENCES providers(id),
    contract_type         TEXT NOT NULL,     -- B2C / B2B
    subjects              TEXT NOT NULL,     -- 과목 코드, 쉼표 구분 (KO,EN,MA,SC,SO)
    available_types       TEXT NOT NULL,     -- 정산 대상 판매 채널, 쉼표 구분 (freepass,ALL)
    started_at            TEXT NOT NULL,     -- KST 날짜 YYYY-MM-DD (시작일 포함)
    expired_at            TEXT NOT NULL,     -- KST 날짜 (마지막 유효일 포함), 2999년 = 무기한
    ratio                 INTEGER NOT NULL DEFAULT 0,  -- 기본 정산비율 (정수 %)
    author_ratio          INTEGER NOT NULL DEFAULT 0,  -- 원저작자 몫 (정수 %), 0 = 해당 없음
    handout_ratio         INTEGER NOT NULL DEFAULT 0,  -- 유인물 등 별도 항목 (정수 %)
    contract_source_group TEXT,              -- 비율 정책 그룹 (의미 미확인)
    is_use_license        INTEGER NOT NULL DEFAULT 0,
    description           TEXT NOT NULL DEFAULT '',    -- 자유 메모 (선급금, 항목별 조건 등)
    created_at            TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contracts_provider ON contracts(provider_id, started_at);
CREATE INDEX IF NOT EXISTS idx_contracts_expired ON contracts(expired_at);

-- 계약 조건은 수정 불가. 허용되는 변경은 expired_at(만료 처리)과 description뿐이다.
CREATE TRIGGER IF NOT EXISTS contracts_terms_immutable
BEFORE UPDATE OF provider_id, contract_type, subjects, available_types, started_at,
                 ratio, author_ratio, handout_ratio, contract_source_group ON contracts
BEGIN
    SELECT RAISE(ABORT, 'contract terms are immutable: expire it and insert a new contract');
END;

-- 정산 원장 (append-only). 금액은 항상 양의 정수(원)이고, 의미는 entry_type이 정한다.
--   미지급금     = ACCRUAL - PAYMENT - OFFSET
--   선급금 잔액  = ADVANCE - OFFSET
--   CANCEL은 cancels_id가 가리키는 항목을 무효화한다 (정정 = CANCEL + 새 항목).
CREATE TABLE IF NOT EXISTS settlement_ledger (
    id          INTEGER PRIMARY KEY,
    provider_id INTEGER NOT NULL REFERENCES providers(id),
    contract_id INTEGER REFERENCES contracts(id),
    period      TEXT NOT NULL,               -- 귀속월 YYYY-MM
    entry_type  TEXT NOT NULL CHECK (entry_type IN ('ACCRUAL', 'PAYMENT', 'ADVANCE', 'OFFSET', 'CANCEL')),
    amount      INTEGER NOT NULL CHECK (amount > 0),
    cancels_id  INTEGER REFERENCES settlement_ledger(id),
    memo        TEXT NOT NULL DEFAULT '',
    recorded_at TEXT NOT NULL,               -- 기록일 KST YYYY-MM-DD
    CHECK ((entry_type = 'CANCEL') = (cancels_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_ledger_provider ON settlement_ledger(provider_id, period);

CREATE TRIGGER IF NOT EXISTS ledger_no_update BEFORE UPDATE ON settlement_ledger
BEGIN
    SELECT RAISE(ABORT, 'settlement_ledger is append-only');
END;

CREATE TRIGGER IF NOT EXISTS ledger_no_delete BEFORE DELETE ON settlement_ledger
BEGIN
    SELECT RAISE(ABORT, 'settlement_ledger is append-only');
END;
