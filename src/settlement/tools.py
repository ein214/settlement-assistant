"""Claude가 호출하는 도구. 각 도구는 repository 조회 결과를 JSON 문자열로 돌려준다.

repository는 개인정보 컬럼을 다루지 않으므로 여기서 반환하는 값은 LLM API로 보내도 되는 데이터만 담는다.
"""

import json

from anthropic import beta_tool

from settlement import repository
from settlement.db.connection import connect

_conn = None


def _db():
    global _conn
    if _conn is None:
        _conn = connect()
    return _conn


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False)


@beta_tool
def search_providers(query: str) -> str:
    """작가 이름으로 검색한다. 정산 정보를 조회하기 전에 반드시 먼저 호출해 provider_id를 확정한다.
    동명이인을 구분할 수 있도록 현재 유효 계약 요약(유형, 과목, 비율)을 함께 반환한다.

    Args:
        query: 사용자가 말한 작가명 또는 일부.
    """
    return _json(repository.search_providers(_db(), query))


@beta_tool
def get_current_contracts(provider_id: int, as_of: str | None = None) -> str:
    """작가의 특정 시점 기준 유효 계약(정산비율, 계약유형, 과목, 기간, 계약 메모)을 조회한다.
    비율은 정수 퍼센트. expired_at이 null이고 indefinite가 true면 무기한 계약이다.

    Args:
        provider_id: 작가 ID.
        as_of: 기준일 YYYY-MM-DD (KST). 생략하면 오늘.
    """
    return _json(repository.get_current_contracts(_db(), provider_id, as_of))


@beta_tool
def get_contract_history(provider_id: int) -> str:
    """작가의 모든 계약을 시작일 순으로 조회한다. 재계약에 따른 정산비율 변경 이력을 확인할 때 쓴다.

    Args:
        provider_id: 작가 ID.
    """
    return _json(repository.get_contract_history(_db(), provider_id))


@beta_tool
def get_expired_contracts(within_days: int = 90) -> str:
    """최근 N일 안에 만료된 계약을 조회한다. renewed(같은 유형의 후속 계약이 현재 유효한지)와
    해당 작가의 미지급금 잔액(payable_balance)을 함께 반환한다. 무기한 계약은 포함되지 않는다.

    Args:
        within_days: 오늘 기준 며칠 전까지 만료된 계약을 볼지.
    """
    return _json(repository.get_expired_contracts(_db(), within_days))


@beta_tool
def get_expiring_contracts(within_days: int = 60) -> str:
    """오늘부터 N일 안에 만료되는 계약을 조회한다. 남은 일수와 후속 계약 등록 여부를 포함한다.

    Args:
        within_days: 조회 기간(일).
    """
    return _json(repository.get_expiring_contracts(_db(), within_days))


@beta_tool
def find_contracts(
    contract_type: str | None = None,
    subject: str | None = None,
    min_ratio: int | None = None,
    max_ratio: int | None = None,
) -> str:
    """현재 유효한 계약을 조건으로 검색한다. 모든 조건은 선택.

    Args:
        contract_type: B2C 또는 B2B.
        subject: 과목 코드(KO, EN, MA, SC, SO) 또는 이름(국어, 영어, 수학, 과학, 사회).
        min_ratio: 기본 정산비율 최소값 (정수 %, 포함).
        max_ratio: 기본 정산비율 최대값 (정수 %, 포함).
    """
    return _json(repository.find_contracts(_db(), contract_type, subject, min_ratio, max_ratio))


@beta_tool
def get_ledger_history(provider_id: int, from_period: str | None = None, to_period: str | None = None) -> str:
    """작가의 귀속월별 정산 원장 요약을 조회한다: 발생(accrual), 지급(payment), 선급 상계(offset),
    선급(advance), 월말 누적 미지급금(payable_balance), 월말 선급금 잔액(advance_balance).
    정정 내역(corrections)과 현재 잔액도 함께 반환한다. 미지급금·미수금·선급금 히스토리 질문에 사용한다.

    Args:
        provider_id: 작가 ID.
        from_period: 시작 귀속월 YYYY-MM (포함). 생략하면 처음부터.
        to_period: 끝 귀속월 YYYY-MM (포함). 생략하면 끝까지.
    """
    return _json(repository.get_ledger_history(_db(), provider_id, from_period, to_period))


@beta_tool
def get_ledger_entries(provider_id: int, period: str) -> str:
    """특정 귀속월의 원장 항목 원본(메모, 기록일, 정정으로 무효화된 항목 여부)을 조회한다.
    월별 요약만으로 설명이 부족할 때(지급 보류 사유, 정정 내용 등) 사용한다.

    Args:
        provider_id: 작가 ID.
        period: 귀속월 YYYY-MM.
    """
    return _json(repository.get_ledger_entries(_db(), provider_id, period))


@beta_tool
def get_outstanding_balances(kind: str = "payable", limit: int = 20) -> str:
    """잔액이 남아 있는 작가를 금액이 큰 순으로 조회한다.

    Args:
        kind: payable(미지급금) 또는 advance(아직 상계되지 않은 선급금).
        limit: 최대 건수.
    """
    return _json(repository.get_outstanding_balances(_db(), kind, limit))


TOOLS = [
    search_providers,
    get_current_contracts,
    get_contract_history,
    get_expired_contracts,
    get_expiring_contracts,
    find_contracts,
    get_ledger_history,
    get_ledger_entries,
    get_outstanding_balances,
]
