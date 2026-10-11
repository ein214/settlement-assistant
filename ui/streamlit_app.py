"""채팅 UI. 실행: streamlit run ui/streamlit_app.py"""

import time
from collections.abc import Iterable, Iterator

import streamlit as st

from settlement.agent import ToolCallEvent, create_agent
from settlement.config import CLAUDE_MODEL, LLM_PROVIDER, OLLAMA_MODEL
from settlement.markdown_safety import safe_lines

MAX_QUESTION_CHARS = 1000

TOOL_LABELS = {
    "search_providers": "작가 검색",
    "get_current_contracts": "현재 계약 조회",
    "get_contract_history": "계약 이력 조회",
    "get_expired_contracts": "만료된 계약 조회",
    "get_expiring_contracts": "만료 예정 계약 조회",
    "find_contracts": "계약 조건 검색",
    "get_ledger_history": "원장 히스토리 조회",
    "get_ledger_entries": "원장 항목 조회",
    "get_outstanding_balances": "잔액 순위 조회",
}


def format_args(arguments: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in arguments.items()) or "인자 없음"


def steps_label(tool_count: int, seconds: float) -> str:
    return f"도구 {tool_count}회 조회 · {seconds:.0f}초" if tool_count else f"답변 생성 · {seconds:.0f}초"


def render_step(call: ToolCallEvent) -> None:
    with st.status(TOOL_LABELS.get(call.name, call.name), type="step", state="complete"):
        st.caption(format_args(call.arguments))


def text_only(events: Iterable[str | ToolCallEvent], steps, calls: list[ToolCallEvent]) -> Iterator[str]:
    """텍스트는 write_stream으로 흘려보내고, 도구 호출은 진행 단계 영역에 바로 그린다."""
    for event in events:
        if isinstance(event, ToolCallEvent):
            calls.append(event)
            with steps:
                render_step(event)
        else:
            yield event


st.set_page_config(page_title="정산 정보 어시스턴트", page_icon=":material/receipt_long:")
st.title("정산 정보 어시스턴트")
model_name = OLLAMA_MODEL if LLM_PROVIDER == "ollama" else CLAUDE_MODEL
st.caption(f"모델: {model_name} · 예: 이도윤 정산비율 알려줘 / 박서준 미수금 히스토리 / 최근 3개월 만료된 계약 / 미지급금 큰 순서")

if "agent" not in st.session_state:
    st.session_state.agent = create_agent()
    st.session_state.chat = []

for msg in st.session_state.chat:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            with st.expander(steps_label(len(msg["calls"]), msg["seconds"]), type="compact"):
                for call in msg["calls"]:
                    render_step(call)
        st.markdown(msg["content"])

if question := st.chat_input("작가명이나 질문을 입력하세요", max_chars=MAX_QUESTION_CHARS, submit_mode="disable"):
    st.session_state.chat.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        start = time.monotonic()
        calls: list[ToolCallEvent] = []
        steps = st.status(":shimmer[조회 중]", type="compact")
        events = st.session_state.agent.ask_stream(question)
        answer = st.write_stream(safe_lines(text_only(events, steps, calls)))
        seconds = time.monotonic() - start
        steps.update(label=steps_label(len(calls), seconds), state="complete")

    st.session_state.chat.append({"role": "assistant", "content": answer, "calls": calls, "seconds": seconds})
