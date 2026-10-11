"""REST API. 실행: uvicorn api.main:app --reload

인증이 없으므로 외부에 노출하지 않는다 (쿠버네티스에서는 ClusterIP + port-forward로만 접근).
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from settlement import repository
from settlement.agent import create_agent
from settlement.db.connection import connect

app = FastAPI(title="Settlement Assistant")
conn = connect()


class ChatRequest(BaseModel):
    # 과도하게 긴 입력으로 LLM 비용·지연을 유발하지 못하도록 길이 제한
    question: str = Field(min_length=1, max_length=1000)


class ChatResponse(BaseModel):
    answer: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    # 단발성 질의. 멀티턴 세션 관리는 이후 단계에서 추가
    return ChatResponse(answer=create_agent().ask(req.question))


@app.get("/providers")
def providers(q: str) -> list[dict]:
    return repository.search_providers(conn, q)


@app.get("/providers/{provider_id}/contracts")
def contracts(provider_id: int, history: bool = False, as_of: str | None = None) -> list[dict]:
    if history:
        return repository.get_contract_history(conn, provider_id, as_of)
    return repository.get_current_contracts(conn, provider_id, as_of)


@app.get("/providers/{provider_id}/ledger")
def ledger(provider_id: int, from_period: str | None = None, to_period: str | None = None) -> dict:
    return repository.get_ledger_history(conn, provider_id, from_period, to_period)


@app.get("/contracts/expired")
def expired(within_days: int = 90) -> list[dict]:
    return repository.get_expired_contracts(conn, within_days)


@app.get("/contracts/expiring")
def expiring(within_days: int = 60) -> list[dict]:
    return repository.get_expiring_contracts(conn, within_days)


@app.get("/balances")
def balances(kind: str = "payable", limit: int = 20) -> list[dict]:
    return repository.get_outstanding_balances(conn, kind, limit)
