"""정산 데이터 조회 계층. 비율·금액·잔액은 반드시 여기서만 나온다 (LLM이 생성·계산하지 않음)."""

import sqlite3
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

INDEFINITE_FROM = "2900-01-01"  # expired_at이 이 날짜 이후면 무기한 계약
SUBJECT_LABELS = {"KO": "국어", "EN": "영어", "MA": "수학", "SC": "과학", "SO": "사회"}

# CANCEL 자체와 CANCEL로 무효화된 항목을 제외한 유효 원장 항목
_EFFECTIVE_LEDGER = """
    entry_type != 'CANCEL'
    AND id NOT IN (SELECT cancels_id FROM settlement_ledger WHERE cancels_id IS NOT NULL)
"""

_SUMS = """
    SUM(CASE WHEN entry_type = 'ACCRUAL' THEN amount ELSE 0 END) AS accrual,
    SUM(CASE WHEN entry_type = 'PAYMENT' THEN amount ELSE 0 END) AS payment,
    SUM(CASE WHEN entry_type = 'OFFSET'  THEN amount ELSE 0 END) AS offset,
    SUM(CASE WHEN entry_type = 'ADVANCE' THEN amount ELSE 0 END) AS advance
"""

_CONTRACT_COLUMNS = """
    c.id AS contract_id, c.provider_id, p.display_name, c.contract_type, c.subjects, c.available_types,
    c.started_at, c.expired_at, c.ratio, c.author_ratio, c.handout_ratio,
    c.contract_source_group, c.is_use_license, c.description
"""


def today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def _as_of(as_of: str | None) -> str:
    return as_of or today_kst().isoformat()


def _split(value: str) -> list[str]:
    return [v for v in value.split(",") if v]


def _contract(row: sqlite3.Row, as_of: str) -> dict:
    d = dict(row)
    d["subjects"] = [SUBJECT_LABELS.get(s, s) for s in _split(d["subjects"])]
    d["available_types"] = _split(d["available_types"])
    d["is_use_license"] = bool(d["is_use_license"])
    d["indefinite"] = d["expired_at"] >= INDEFINITE_FROM
    if d["started_at"] > as_of:
        d["status"] = "scheduled"
    elif d["expired_at"] < as_of:
        d["status"] = "expired"
    else:
        d["status"] = "active"
    if d["indefinite"]:
        d["expired_at"] = None
    return d


def _payable(accrual: int, payment: int, offset: int) -> int:
    return accrual - payment - offset


def _advance_outstanding(advance: int, offset: int) -> int:
    return advance - offset


# ---------- 작가 / 계약 ----------

def search_providers(conn: sqlite3.Connection, query: str, as_of: str | None = None) -> list[dict]:
    """이름으로 작가 검색. 동명이인 구분을 위해 현재 유효 계약 요약을 함께 반환."""
    as_of = _as_of(as_of)
    providers = [dict(r) for r in conn.execute(
        "SELECT id AS provider_id, display_name, provider_type FROM providers WHERE display_name LIKE ? ORDER BY id",
        (f"%{query.strip()}%",),
    )]
    for p in providers:
        p["active_contracts"] = [
            {k: c[k] for k in ("contract_id", "contract_type", "subjects", "ratio")}
            for c in get_current_contracts(conn, p["provider_id"], as_of)
        ]
    return providers


def get_current_contracts(conn: sqlite3.Connection, provider_id: int, as_of: str | None = None) -> list[dict]:
    as_of = _as_of(as_of)
    rows = conn.execute(
        f"""SELECT {_CONTRACT_COLUMNS} FROM contracts c JOIN providers p ON p.id = c.provider_id
            WHERE c.provider_id = ? AND c.started_at <= ? AND c.expired_at >= ?
            ORDER BY c.contract_type, c.started_at""",
        (provider_id, as_of, as_of),
    )
    return [_contract(r, as_of) for r in rows]


def get_contract_history(conn: sqlite3.Connection, provider_id: int, as_of: str | None = None) -> list[dict]:
    """계약 행을 시작일 순으로 반환. 재계약으로 인한 비율 변경 이력이 된다."""
    as_of = _as_of(as_of)
    rows = conn.execute(
        f"""SELECT {_CONTRACT_COLUMNS} FROM contracts c JOIN providers p ON p.id = c.provider_id
            WHERE c.provider_id = ? ORDER BY c.contract_type, c.started_at""",
        (provider_id,),
    )
    return [_contract(r, as_of) for r in rows]


def get_expired_contracts(conn: sqlite3.Connection, within_days: int = 90, as_of: str | None = None) -> list[dict]:
    """최근 within_days일 안에 만료된 계약. 갱신 여부와 해당 작가의 미지급금을 함께 반환."""
    as_of = _as_of(as_of)
    since = (date.fromisoformat(as_of) - timedelta(days=within_days)).isoformat()
    rows = conn.execute(
        f"""SELECT {_CONTRACT_COLUMNS},
                   (SELECT n.id FROM contracts n
                    WHERE n.provider_id = c.provider_id AND n.contract_type = c.contract_type
                      AND n.started_at > c.started_at AND n.expired_at >= ?
                    ORDER BY n.started_at LIMIT 1) AS successor_contract_id
            FROM contracts c JOIN providers p ON p.id = c.provider_id
            WHERE c.expired_at >= ? AND c.expired_at < ?
            ORDER BY c.expired_at DESC""",
        (as_of, since, as_of),
    )
    result = []
    for r in rows:
        d = _contract(r, as_of)
        d["renewed"] = d["successor_contract_id"] is not None
        # 작은 모델이 boolean을 놓치지 않도록 사람이 읽는 상태 문구를 함께 둔다
        d["renewal_status"] = f"갱신됨 (후속 계약 {d['successor_contract_id']})" if d["renewed"] else "미갱신 (계약 종료)"
        d["payable_balance"] = get_balances(conn, d["provider_id"])["payable"]
        result.append(d)
    return result


def get_expiring_contracts(conn: sqlite3.Connection, within_days: int = 60, as_of: str | None = None) -> list[dict]:
    """오늘부터 within_days일 안에 만료되는 계약 (무기한 제외). 후속 계약 등록 여부 포함."""
    as_of = _as_of(as_of)
    until = (date.fromisoformat(as_of) + timedelta(days=within_days)).isoformat()
    rows = conn.execute(
        f"""SELECT {_CONTRACT_COLUMNS},
                   (SELECT n.id FROM contracts n
                    WHERE n.provider_id = c.provider_id AND n.contract_type = c.contract_type
                      AND n.started_at > c.started_at
                    ORDER BY n.started_at LIMIT 1) AS successor_contract_id
            FROM contracts c JOIN providers p ON p.id = c.provider_id
            WHERE c.expired_at >= ? AND c.expired_at <= ? AND c.expired_at < ?
            ORDER BY c.expired_at""",
        (as_of, until, INDEFINITE_FROM),
    )
    result = []
    for r in rows:
        d = _contract(r, as_of)
        d["renewal_registered"] = d["successor_contract_id"] is not None
        d["renewal_status"] = (
            f"후속 계약 등록됨 ({d['successor_contract_id']})" if d["renewal_registered"] else "후속 계약 없음 (재계약 필요)"
        )
        d["days_left"] = (date.fromisoformat(d["expired_at"]) - date.fromisoformat(as_of)).days
        result.append(d)
    return result


def find_contracts(
    conn: sqlite3.Connection,
    contract_type: str | None = None,
    subject: str | None = None,
    min_ratio: int | None = None,
    max_ratio: int | None = None,
    as_of: str | None = None,
) -> list[dict]:
    """현재 유효한 계약을 조건으로 검색. subject는 코드(KO) 또는 이름(국어)."""
    as_of = _as_of(as_of)
    sql = f"""SELECT {_CONTRACT_COLUMNS} FROM contracts c JOIN providers p ON p.id = c.provider_id
              WHERE c.started_at <= ? AND c.expired_at >= ?"""
    params: list = [as_of, as_of]
    if contract_type:
        sql += " AND c.contract_type = ?"
        params.append(contract_type.upper())
    if subject:
        code = next((k for k, v in SUBJECT_LABELS.items() if v == subject), subject.upper())
        sql += " AND (',' || c.subjects || ',') LIKE ?"
        params.append(f"%,{code},%")
    if min_ratio is not None:
        sql += " AND c.ratio >= ?"
        params.append(min_ratio)
    if max_ratio is not None:
        sql += " AND c.ratio <= ?"
        params.append(max_ratio)
    rows = conn.execute(sql + " ORDER BY c.ratio DESC, c.provider_id", params)
    return [_contract(r, as_of) for r in rows]


# ---------- 원장: 미지급금 / 선급금 ----------

def get_balances(conn: sqlite3.Connection, provider_id: int) -> dict:
    row = conn.execute(
        f"SELECT {_SUMS} FROM settlement_ledger WHERE provider_id = ? AND {_EFFECTIVE_LEDGER}",
        (provider_id,),
    ).fetchone()
    accrual, payment, offset, advance = (row[k] or 0 for k in ("accrual", "payment", "offset", "advance"))
    return {
        "provider_id": provider_id,
        "payable": _payable(accrual, payment, offset),
        "advance_outstanding": _advance_outstanding(advance, offset),
    }


def get_ledger_history(
    conn: sqlite3.Connection, provider_id: int, from_period: str | None = None, to_period: str | None = None
) -> dict:
    """귀속월별 발생·지급·상계·선급과 월말 누적 잔액. 정정(CANCEL) 내역을 별도로 반환."""
    rows = conn.execute(
        f"""SELECT period, {_SUMS} FROM settlement_ledger
            WHERE provider_id = ? AND {_EFFECTIVE_LEDGER}
            GROUP BY period ORDER BY period""",
        (provider_id,),
    ).fetchall()

    # 누적 잔액은 조회 구간 이전 기간까지 포함해 계산한 뒤 구간으로 자른다
    monthly, payable, advance_out = [], 0, 0
    for r in rows:
        payable += _payable(r["accrual"], r["payment"], r["offset"])
        advance_out += _advance_outstanding(r["advance"], r["offset"])
        if (from_period and r["period"] < from_period) or (to_period and r["period"] > to_period):
            continue
        monthly.append({**dict(r), "payable_balance": payable, "advance_balance": advance_out})

    corrections = [dict(r) for r in conn.execute(
        """SELECT c.period, c.recorded_at, c.memo, o.id AS cancelled_entry_id,
                  o.entry_type AS cancelled_type, o.amount AS cancelled_amount, o.memo AS cancelled_memo
           FROM settlement_ledger c JOIN settlement_ledger o ON o.id = c.cancels_id
           WHERE c.provider_id = ? AND c.entry_type = 'CANCEL'
             AND (? IS NULL OR c.period >= ?) AND (? IS NULL OR c.period <= ?)
           ORDER BY c.period, c.id""",
        (provider_id, from_period, from_period, to_period, to_period),
    )]
    return {"provider_id": provider_id, "monthly": monthly, "corrections": corrections,
            **{k: v for k, v in get_balances(conn, provider_id).items() if k != "provider_id"}}


def get_ledger_entries(conn: sqlite3.Connection, provider_id: int, period: str) -> list[dict]:
    """특정 귀속월의 원장 항목 원본 (무효화 여부 포함)."""
    return [dict(r) | {"cancelled": bool(r["cancelled"])} for r in conn.execute(
        """SELECT l.id, l.contract_id, l.period, l.entry_type, l.amount, l.cancels_id, l.memo, l.recorded_at,
                  EXISTS (SELECT 1 FROM settlement_ledger x WHERE x.cancels_id = l.id) AS cancelled
           FROM settlement_ledger l WHERE l.provider_id = ? AND l.period = ? ORDER BY l.id""",
        (provider_id, period),
    )]


def get_outstanding_balances(conn: sqlite3.Connection, kind: str = "payable", limit: int = 20) -> list[dict]:
    """잔액이 남은 작가 목록. kind: payable(미지급금) / advance(미상계 선급금)."""
    rows = conn.execute(
        f"""SELECT l.provider_id, p.display_name, {_SUMS}
            FROM (SELECT * FROM settlement_ledger WHERE {_EFFECTIVE_LEDGER}) l
            JOIN providers p ON p.id = l.provider_id
            GROUP BY l.provider_id""",
    ).fetchall()
    result = [
        {
            "provider_id": r["provider_id"],
            "display_name": r["display_name"],
            "payable": _payable(r["accrual"], r["payment"], r["offset"]),
            "advance_outstanding": _advance_outstanding(r["advance"], r["offset"]),
        }
        for r in rows
    ]
    key = "advance_outstanding" if kind == "advance" else "payable"
    return sorted((r for r in result if r[key] > 0), key=lambda r: r[key], reverse=True)[:limit]
