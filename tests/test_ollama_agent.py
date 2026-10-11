"""Ollama 에이전트의 도구 호출 루프를 가짜 클라이언트로 검증 (실제 모델 불필요)."""

import json
from types import SimpleNamespace

import pytest
from ollama import Message

from settlement import tools
from settlement.agent import OllamaSettlementAgent, ToolCallEvent
from settlement.db.connection import connect
from settlement.db.seed import seed


@pytest.fixture(autouse=True)
def seeded_db(tmp_path, monkeypatch):
    conn = connect(tmp_path / "test.db")
    seed(conn)
    monkeypatch.setattr(tools, "_conn", conn)
    yield
    conn.close()


class FakeClient:
    """미리 정한 응답을 순서대로 돌려주고, 받은 메시지를 기록한다."""

    def __init__(self, replies: list[Message]):
        self.replies = list(replies)
        self.calls: list[list] = []

    def chat(self, **kwargs):
        self.calls.append(list(kwargs["messages"]))
        # stream=True이므로 응답 하나를 청크 하나로 돌려준다
        return iter([SimpleNamespace(message=self.replies.pop(0))])


def tool_call(name: str, arguments: dict) -> Message:
    return Message(
        role="assistant",
        content="",
        tool_calls=[Message.ToolCall(function=Message.ToolCall.Function(name=name, arguments=arguments))],
    )


def test_runs_tool_and_returns_final_answer():
    client = FakeClient([tool_call("search_providers", {"query": "이도윤"}), Message(role="assistant", content="이도윤 60%")])
    agent = OllamaSettlementAgent(client=client, model="fake")

    assert agent.ask("이도윤 정산비율") == "이도윤 60%"
    tool_result = client.calls[1][-1]
    assert tool_result["role"] == "tool"
    assert json.loads(tool_result["content"])[0]["provider_id"] == 1003


def test_bad_arguments_are_returned_as_error_not_raised():
    client = FakeClient([tool_call("get_balances_typo", {}), tool_call("get_ledger_history", {"wrong": 1}),
                         Message(role="assistant", content="확인할 수 없습니다")])
    agent = OllamaSettlementAgent(client=client, model="fake")

    assert agent.ask("잔액") == "확인할 수 없습니다"
    assert "unknown tool" in client.calls[1][-1]["content"]
    assert "error" in json.loads(client.calls[2][-1]["content"])


def test_stops_after_max_tool_rounds():
    client = FakeClient([tool_call("list_x", {})] * OllamaSettlementAgent.MAX_TOOL_ROUNDS)
    agent = OllamaSettlementAgent(client=client, model="fake")

    assert "중단" in agent.ask("무한 루프")


def test_stream_yields_tool_events_then_text():
    client = FakeClient([tool_call("search_providers", {"query": "이도윤"}), Message(role="assistant", content="60%")])
    agent = OllamaSettlementAgent(client=client, model="fake")

    events = list(agent.ask_stream("이도윤"))
    assert events == [ToolCallEvent("search_providers", {"query": "이도윤"}), "60%"]
