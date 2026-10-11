import sqlite3

import pytest

from settlement import repository
from settlement.db.connection import connect
from settlement.db.seed import seed

AS_OF = "2026-10-06"  # 시드 데이터 기준일


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    seed(c)
    yield c
    c.close()


# ---------- 작가 / 계약 ----------

def test_search_returns_homonyms_with_contract_summary(conn):
    found = repository.search_providers(conn, "김하늘", AS_OF)
    assert [p["provider_id"] for p in found] == [1001, 1002]
    assert [p["active_contracts"][0]["subjects"] for p in found] == [["국어"], ["영어"]]


def test_current_contract_marks_indefinite(conn):
    [c] = repository.get_current_contracts(conn, 1003, AS_OF)
    assert c["ratio"] == 60
    assert c["indefinite"] is True
    assert c["expired_at"] is None
    assert c["status"] == "active"


def test_current_contract_as_of_past_date(conn):
    [c] = repository.get_current_contracts(conn, 1003, "2024-06-01")
    assert c["contract_id"] == 5003
    assert c["ratio"] == 50


def test_contract_history_shows_ratio_change(conn):
    history = repository.get_contract_history(conn, 1003, AS_OF)
    assert [(c["ratio"], c["status"]) for c in history] == [(50, "expired"), (60, "active")]


def test_expired_contracts_flag_renewal_and_payable(conn):
    expired = {c["contract_id"]: c for c in repository.get_expired_contracts(conn, 90, AS_OF)}
    assert set(expired) == {5005, 5008}
    assert expired[5005]["renewed"] is False
    assert expired[5005]["payable_balance"] == 650_000
    assert expired[5008]["renewed"] is True
    assert expired[5008]["renewal_status"] == "갱신됨 (후속 계약 5009)"
    assert expired[5005]["renewal_status"] == "미갱신 (계약 종료)"


def test_expiring_contracts_exclude_indefinite(conn):
    expiring = repository.get_expiring_contracts(conn, 60, AS_OF)
    assert [(c["contract_id"], c["days_left"]) for c in expiring] == [(5007, 25), (5006, 55)]


def test_find_contracts_by_subject_name_and_ratio(conn):
    found = repository.find_contracts(conn, subject="국어", min_ratio=55, as_of=AS_OF)
    assert {c["contract_id"] for c in found} == {5001, 5009}


def test_find_contracts_matches_multi_subject(conn):
    found = repository.find_contracts(conn, subject="SO", as_of=AS_OF)
    assert [c["contract_id"] for c in found] == [5007]


# ---------- 원장 ----------

def test_balances_exclude_cancelled_entries(conn):
    assert repository.get_balances(conn, 1003) == {"provider_id": 1003, "payable": 1_250_000, "advance_outstanding": 0}


def test_advance_fully_offset(conn):
    assert repository.get_balances(conn, 1001) == {"provider_id": 1001, "payable": 250_000, "advance_outstanding": 0}


def test_ledger_history_running_balances(conn):
    history = repository.get_ledger_history(conn, 1001)
    assert [(m["period"], m["payable_balance"], m["advance_balance"]) for m in history["monthly"]] == [
        ("2026-05", 0, 3_000_000),
        ("2026-06", 0, 2_200_000),
        ("2026-07", 0, 1_300_000),
        ("2026-08", 0, 600_000),
        ("2026-09", 250_000, 0),
    ]


def test_ledger_history_period_filter_keeps_prior_balance(conn):
    history = repository.get_ledger_history(conn, 1001, from_period="2026-08")
    assert [m["period"] for m in history["monthly"]] == ["2026-08", "2026-09"]
    assert history["monthly"][0]["advance_balance"] == 600_000


def test_ledger_history_reports_correction(conn):
    history = repository.get_ledger_history(conn, 1003)
    july = next(m for m in history["monthly"] if m["period"] == "2026-07")
    assert july["accrual"] == 1_150_000
    [correction] = history["corrections"]
    assert correction["cancelled_entry_id"] == 12
    assert correction["cancelled_amount"] == 1_200_000


def test_ledger_entries_mark_cancelled(conn):
    entries = {e["id"]: e for e in repository.get_ledger_entries(conn, 1003, "2026-07")}
    assert entries[12]["cancelled"] is True
    assert entries[14]["cancelled"] is False


def test_outstanding_balances_sorted(conn):
    payable = repository.get_outstanding_balances(conn, "payable")
    assert [(r["display_name"], r["payable"]) for r in payable] == [
        ("패스 영어팀", 2_100_000),
        ("이도윤", 1_250_000),
        ("박서준", 650_000),
        ("김하늘", 250_000),
    ]
    assert repository.get_outstanding_balances(conn, "advance") == []


# ---------- 불변성 ----------

def test_ledger_is_append_only(conn):
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE settlement_ledger SET amount = 1 WHERE id = 2")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM settlement_ledger WHERE id = 2")


def test_contract_terms_are_immutable_but_can_expire(conn):
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE contracts SET ratio = 70 WHERE id = 5004")
    conn.execute("UPDATE contracts SET expired_at = '2026-12-31' WHERE id = 5004")


def test_unknown_provider_returns_empty(conn):
    assert repository.search_providers(conn, "없는작가", AS_OF) == []
    assert repository.get_current_contracts(conn, 9999, AS_OF) == []
    assert repository.get_balances(conn, 9999)["payable"] == 0
