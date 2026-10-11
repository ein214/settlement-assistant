# CLAUDE.md

사내 정산 담당자용 정산 정보 조회 어시스턴트 (정산비율·변경이력·미수금·계약 만료). Python 3.11+, Anthropic SDK tool runner 또는 Ollama 로컬 모델, SQLite, FastAPI, Streamlit.

원본 도메인은 교육 콘텐츠 마켓플레이스의 작가(provider) 정산이다. 원본 DB에는 접근할 수 없으며, 스키마 구조만 참고해 가상 데이터로 재현한다.

## Commands
- Setup: `pip install -e ".[dev]"` then `python -m settlement.db.seed`
- Test: `pytest`
- UI: `streamlit run ui/streamlit_app.py` / API: `uvicorn api.main:app --reload`
- Docker: `docker build -t settlement-assistant .` / 배포는 `main` 푸시 → CI → Argo CD (README 참고)
- 의존성을 바꾸면 `requirements.lock`도 다시 생성한다 (새 venv에서 `pip install . && pip freeze`)

## Data & Privacy
- 실제 데이터(이름, 연락처, 계좌번호, 주민·사업자등록번호, 주소, 신분증·통장 이미지 URL)는 저장소, seed, 테스트, 프롬프트 어디에도 넣지 않는다. seed는 전부 가상 데이터로 만든다.
- 개인정보 컬럼은 스키마에 두더라도 도구(`tools.py`)가 반환하는 컬럼은 화이트리스트로 제한한다. LLM API로 개인정보를 보내지 않는다. 필요하면 마스킹 (`홍*동`, `***-****-1234`).

## Domain Policies
- **비율은 정수 퍼센트**로 저장한다 (`ratio = 60` → 60%). 금액은 원 단위 정수다. float 연산을 쓰지 않는다.
- 계약 비율 컬럼: `ratio`(기본 정산비율), `author_ratio`(원저작자 몫), `handout_ratio`(유인물 등 별도 항목). 0은 "해당 없음"이다.
- `contract_type`: `B2C`(일반 판매) / `B2B`(패스 등 제휴). `available_type`: 정산 대상 판매 채널 (`freepass`, `ALL` 등).
- `contract_source_group`(예: `기본6070`, `기본5060`, `자체창작60`)은 비율 정책 그룹이다. 정확한 의미는 미확인이므로 추론해서 설명하지 않는다.
- **무기한 계약은 `expired_at`이 2999년**인 센티널 값이다. 만료/만료예정 조회에서 제외하고 화면에는 "무기한"으로 표시한다.
- 날짜는 **KST 기준 날짜(YYYY-MM-DD)**로 저장·비교한다. `started_at`은 시작일, `expired_at`은 마지막 유효일이며 둘 다 포함이다. 원본은 timestamptz에 만료 시각이 `00:00`, `08:59:59` 등으로 섞여 있어 날짜 단위로 정규화했다.
- `description`은 자유 메모이며 선급금, 항목별 별도 비율 같은 실제 조건이 들어 있을 수 있다. 답변에는 "계약 메모"로 구분해서 보여주고, 비율 컬럼과 내용이 다르면 불일치를 알린다. 메모에서 숫자를 뽑아 정식 비율처럼 답하지 않는다.
- **불변성**: 계약 조건과 정산 금액은 UPDATE로 덮어쓰지 않는다. 계약 변경은 기존 계약을 만료 처리하고 새 행을 추가하며, 정산 금액 정정은 취소 행과 새 행을 추가한다. 이력은 이 행들로 재구성한다.
- 이 프로젝트에서 "미수금"은 **작가에게 아직 지급하지 않은 정산금(미지급금)**을 뜻한다. 선급금 잔액도 함께 다룬다.
- 잔액은 저장하지 않고 `settlement_ledger`(append-only, 트리거로 UPDATE/DELETE 차단)에서 계산한다. 금액은 항상 양수이고 의미는 `entry_type`이 정한다.
  - 미지급금 = ACCRUAL − PAYMENT − OFFSET, 선급금 잔액 = ADVANCE − OFFSET
  - 정정은 `CANCEL`(cancels_id로 원 항목 지정) + 새 항목. CANCEL 행과 취소된 항목은 합계에서 제외한다.
  - `period`는 귀속월(YYYY-MM)이다. 지급일은 `recorded_at`/메모에 남긴다.
- 계약 조건 컬럼은 트리거로 UPDATE를 막는다. `expired_at`(만료 처리)과 `description`만 수정할 수 있다.
- 합계·잔액 계산은 SQL/파이썬에서 하고 LLM은 결과만 설명한다.

## Security
- 비밀값은 `.gitignore`/`.dockerignore`로 저장소와 이미지에서 제외한다. 현재 배포는 API 키 없이 Ollama만 쓴다.
- LLM 출력은 `markdown_safety.safe_lines`를 거쳐 렌더링한다. 도구는 읽기 전용으로 유지하고, 쓰기 도구를 추가하려면 사람 승인 단계를 둔다.
- API는 인증이 없으므로 외부 노출(LoadBalancer/Ingress/NodePort)을 하지 않는다.
- CI 액션은 커밋 SHA로 고정하고 잡별 최소 권한(`permissions`)을 유지한다.
- 사람이 쓰는 커밋 메시지에는 `[skip ci]` 문자열을 넣지 않는다 (본문에 있어도 GitHub가 CI를 건너뛴다). 이 표시는 CI의 배포 태그 커밋 전용이다. CI만 다시 돌리려면 `gh workflow run CI`.
- 커밋 작성자 이메일은 GitHub noreply 주소를 쓴다 (저장소 로컬 git 설정).

## Code Rules
- 비율·금액·날짜·계약번호는 반드시 `repository.py` 조회 결과에서만 나와야 한다. 프롬프트나 코드에서 LLM이 숫자를 생성·계산하게 만들지 않는다.
- 새 조회 기능은 `repository.py` 함수 + 테스트 → `tools.py` 도구 → 필요 시 `api/main.py` 순서로 추가한다.
- `SettlementAgent.messages`는 append-only로 유지한다 (이전 턴 수정 시 thinking 블록 검증 오류).
- LLM은 `LLM_PROVIDER`(`anthropic`/`ollama`)로 고른다. 에이전트는 `create_agent()`로 만들고, 두 구현(`SettlementAgent`, `OllamaSettlementAgent`)은 같은 `SYSTEM_PROMPT`와 `TOOLS`를 공유한다. 도구나 프롬프트 변경이 양쪽에서 동작하는지 확인한다.
- 두 에이전트는 `ask_stream()`(텍스트 조각과 `ToolCallEvent`를 순서대로 yield)을 구현하고, `ask()`는 그 텍스트를 모은 것이다. UI는 `ask_stream`으로 답변을 스트리밍하고 도구 호출을 진행 단계로 표시한다.
- 모델: `CLAUDE_MODEL`(기본 `claude-opus-5-5`), `OLLAMA_MODEL`(기본 `qwen3:8b`, M1 16GB 기준). Ollama 서버는 `brew services start ollama`로 띄운다.
- 테스트는 시드 기준일 `2026-10-06`을 `as_of`로 고정한다. 날짜 기본값은 `repository.today_kst()`를 쓴다.
- seed 시나리오(동명이인, 무기한, 재계약, 만료+미지급, 메모 불일치, 선급 상계, 정정)는 테스트가 의존하므로 바꾸면 테스트도 함께 고친다.
