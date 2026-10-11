"""정산 조회 에이전트: 질문 해석 → 도구 호출 → 답변 정리.

LLM_PROVIDER에 따라 Claude(tool runner) 또는 Ollama 로컬 모델을 쓴다. 도구와 프롬프트는 공유한다.
"""

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import anthropic
import ollama

from settlement.config import CLAUDE_EFFORT, CLAUDE_MODEL, LLM_PROVIDER, OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_NUM_CTX
from settlement.repository import today_kst
from settlement.tools import TOOLS


@dataclass(frozen=True)
class ToolCallEvent:
    """ask_stream이 텍스트 조각 사이에 내보내는 도구 호출 알림 (UI 진행 표시용)."""

    name: str
    arguments: dict


def _collect_text(events: Iterable[str | ToolCallEvent]) -> str:
    return "".join(e for e in events if isinstance(e, str))

SYSTEM_PROMPT = """당신은 사내 정산 담당자를 돕는 작가 정산 정보 조회 어시스턴트입니다.

사실의 출처:
- 정산비율, 금액, 잔액, 날짜, 계약 ID 등 모든 사실은 도구 조회 결과에서만 가져옵니다. 추측하거나 숫자를 직접 계산·합산하지 않습니다. 잔액과 합계는 도구가 계산한 값을 그대로 씁니다.
- 조회 결과가 없으면 "등록된 정보가 없습니다"라고 답합니다.

작가 확정:
- 작가 이름이 나오면 먼저 search_providers로 provider_id를 확정합니다. 동명이인이 있고 질문만으로 특정할 수 없으면 계약유형·과목을 붙여 후보를 보여주고 되묻습니다.

도메인 규칙:
- 비율은 정수 퍼센트입니다 (ratio 60 → 60%). ratio는 기본 정산비율, author_ratio는 원저작자 몫, handout_ratio는 유인물 등 별도 항목이며 0이면 "해당 없음"으로 표시합니다.
- indefinite가 true인 계약은 만료일 대신 "무기한"으로 표시합니다.
- contract_source_group은 값만 보여주고 의미를 추측해 설명하지 않습니다.
- description은 "계약 메모"로 따로 보여줍니다. 메모에 비율 컬럼과 다른 조건(항목별 별도 비율, 선급금 등)이 있으면 불일치 또는 추가 조건이 있다고 알리고, 메모의 숫자를 정식 비율처럼 답하지 않습니다.
- 사용자가 "미수금"이라고 하면 작가에게 아직 지급하지 않은 정산금, 즉 미지급금(payable)을 뜻합니다. 선급금 잔액(advance_outstanding)이 있으면 함께 보여줍니다.
- 원장 기간은 귀속월(정산 대상 월) 기준입니다. 정정(corrections)이 있으면 무엇이 취소되고 다시 생성됐는지 설명합니다.

답변 형식:
- 현재 계약은 표로, 비율 변경 이력과 원장 히스토리는 시간순 표나 목록으로 정리합니다. 금액은 천 단위 쉼표와 "원"으로 표기합니다.
- 근거가 되는 계약 ID를 함께 표시합니다.
- 작가 목록에는 동명이인을 구분할 수 있도록 provider_id를 함께 표시합니다.
- 만료·만료 예정 계약은 renewal_status 값을 그대로 보여줍니다.
- 계약 만료가 60일 이내이거나, 만료된 계약에 미지급금이 남아 있으면 함께 알려줍니다.

오늘 날짜(KST): {today}"""


class SettlementAgent:
    """대화 이력을 보존하는 멀티턴 에이전트. 이력은 append-only로만 쌓는다."""

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.messages: list = []
        self.system = SYSTEM_PROMPT.format(today=today_kst().isoformat())

    def ask(self, question: str) -> str:
        return _collect_text(self.ask_stream(question))

    def ask_stream(self, question: str) -> Iterator[str | ToolCallEvent]:
        self.messages.append({"role": "user", "content": question})
        runner = self.client.beta.messages.tool_runner(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            system=self.system,
            tools=TOOLS,
            messages=list(self.messages),
            thinking={"type": "adaptive"},
            output_config={"effort": CLAUDE_EFFORT},
            # 정책상 거절 시 서버가 다른 모델로 자동 재시도
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            stream=True,
        )

        last = None
        for stream in runner:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield event.delta.text
            last = stream.get_final_message()
            # runner는 자체 이력을 노출하지 않으므로 다음 턴을 위해 직접 미러링
            self.messages.append({"role": "assistant", "content": last.content})
            for block in last.content:
                if block.type == "tool_use":
                    yield ToolCallEvent(block.name, dict(block.input))
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                self.messages.append(tool_response)

        if last is None:
            yield "응답을 받지 못했습니다."
        elif last.stop_reason == "refusal":
            yield "\n\n요청을 처리할 수 없습니다. 질문을 바꿔 다시 시도해 주세요."


# 작은 로컬 모델이 자주 놓치는 부분을 보강하는 지시
_OLLAMA_EXTRA = """

추가 지시:
- 반드시 한국어로 답합니다.
- 비율 인자는 정수 퍼센트로 넘깁니다 (60% → 60, 0.6이 아님).
- 작가 관련 질문은 search_providers를 먼저 호출하고, 그 결과의 provider_id로 다음 도구를 호출합니다."""


class OllamaSettlementAgent:
    """Ollama 로컬 모델용 에이전트. 도구 호출 루프를 직접 돌린다."""

    MAX_TOOL_ROUNDS = 8

    def __init__(self, client: ollama.Client | None = None, model: str = OLLAMA_MODEL):
        self.client = client or ollama.Client(host=OLLAMA_HOST)
        self.model = model
        self.messages: list = [
            {"role": "system", "content": SYSTEM_PROMPT.format(today=today_kst().isoformat()) + _OLLAMA_EXTRA}
        ]
        self._tools = {t.name: t for t in TOOLS}
        self._schemas = [
            {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}}
            for t in TOOLS
        ]

    def ask(self, question: str) -> str:
        return _collect_text(self.ask_stream(question))

    def ask_stream(self, question: str) -> Iterator[str | ToolCallEvent]:
        self.messages.append({"role": "user", "content": question})
        for _ in range(self.MAX_TOOL_ROUNDS):
            content: list[str] = []
            tool_calls: list[ollama.Message.ToolCall] = []
            for chunk in self.client.chat(
                model=self.model,
                messages=self.messages,
                tools=self._schemas,
                stream=True,
                think=False,  # M1에서 응답 속도 우선
                options={"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
            ):
                if chunk.message.content:
                    content.append(chunk.message.content)
                    yield chunk.message.content
                tool_calls.extend(chunk.message.tool_calls or [])

            self.messages.append(ollama.Message(role="assistant", content="".join(content), tool_calls=tool_calls or None))
            if not tool_calls:
                if not content:
                    yield "응답을 받지 못했습니다."
                return
            for call in tool_calls:
                yield ToolCallEvent(call.function.name, dict(call.function.arguments))
                self.messages.append({
                    "role": "tool",
                    "tool_name": call.function.name,
                    "content": self._run_tool(call.function.name, call.function.arguments),
                })
        yield "도구 호출이 너무 많아 중단했습니다. 질문을 더 구체적으로 해 주세요."

    def _run_tool(self, name: str, arguments: dict) -> str:
        # 작은 모델은 없는 도구나 잘못된 인자를 보내기도 하므로, 오류를 결과로 돌려줘 스스로 고치게 한다
        tool = self._tools.get(name)
        if tool is None:
            return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
        try:
            return tool.call(dict(arguments))
        except (TypeError, ValueError) as e:
            return json.dumps({"error": f"{e}: {e.__cause__ or ''}"}, ensure_ascii=False)


def create_agent() -> SettlementAgent | OllamaSettlementAgent:
    if LLM_PROVIDER == "ollama":
        return OllamaSettlementAgent()
    return SettlementAgent()
