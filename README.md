# Settlement Assistant

사내 정산 담당자가 작가 이름으로 정산비율, 비율 변경 이력, 미지급금·선급금 히스토리, 만료(예정) 계약을 조회하는 LLM 어시스턴트.
Claude가 질문을 해석해 조회 도구를 호출하고, **숫자는 DB 조회 결과에서만** 가져온다. 데이터는 전부 가상이다.

```
질문 → Claude (tool use) → search_providers / get_current_contracts / get_ledger_history ... → SQLite
                         ← 조회 결과(JSON) ←
     ← 표·이력 정리 + 근거(계약번호, 조항)
```

## 빠른 시작

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # LLM_PROVIDER 선택 (ollama면 API 키 불필요)
python -m settlement.db.seed      # 더미 데이터 생성 (data/settlement.db)

streamlit run ui/streamlit_app.py # 채팅 UI
uvicorn api.main:app --reload     # REST API (http://localhost:8000/docs)
pytest                            # 조회 계층 테스트
```

### LLM 선택

| `LLM_PROVIDER` | 준비 | 특징 |
|---|---|---|
| `ollama` (무료) | `brew install ollama && brew services start ollama && ollama pull qwen3:8b` | 로컬 실행, 데이터 외부 전송 없음, 성능·속도는 낮음 |
| `anthropic` | `.env`에 `ANTHROPIC_API_KEY` | 판단(동명이인 되묻기, 메모 불일치 경고) 품질이 높음 |

## 예시 질문

| 질문 | 사용 도구 |
|---|---|
| 이도윤 정산비율 알려줘 / 비율 바뀐 적 있어? | `search_providers` → `get_current_contracts`, `get_contract_history` |
| 김하늘 미수금 히스토리 | 동명이인 되묻기 → `get_ledger_history` |
| 최근 3개월 만료된 계약 | `get_expired_contracts` (갱신 여부, 미지급금 포함) |
| 60일 안에 만료되는 계약 | `get_expiring_contracts` |
| 미지급금 큰 순서로 / 선급금 남은 작가 | `get_outstanding_balances` |
| 영어 B2B 계약 / 국어 55% 이상 | `find_contracts` |

## 구조

| 경로 | 역할 |
|---|---|
| `src/settlement/db/schema.sql` | 작가·계약·정산 원장 스키마 (계약 조건 불변, 원장 append-only를 트리거로 강제) |
| `src/settlement/db/seed.py` | 개발용 더미 데이터 |
| `src/settlement/repository.py` | SQL 조회 함수 |
| `src/settlement/tools.py` | Claude가 호출하는 도구 (`@beta_tool`) |
| `src/settlement/agent.py` | 공유 시스템 프롬프트 + Claude(tool runner) / Ollama(직접 루프) 에이전트 |
| `api/main.py` | FastAPI 엔드포인트 |
| `ui/streamlit_app.py` | 채팅 UI |

## 로드맵

1. ✅ 가상 DB(계약·원장) + tool use 챗봇 + Streamlit
2. 계약서 PDF → 정산조건 추출 → 담당자 승인 후 DB 반영
3. 계약서 원문 RAG + 출처 링크
4. Slack 연동, 사용자 권한, 감사 로그

## 배포 (로컬 쿠버네티스 + GitOps)

외부에 공개하지 않는 학습용 배포다. API 키 없이 Mac의 Ollama를 사용한다.

```
push → GitHub Actions: 테스트 + pip-audit → arm64 이미지 빌드 → GHCR 푸시 → k8s/ 이미지 태그 커밋
                                                                          ↓
                         로컬 쿠버네티스(Docker Desktop)의 Argo CD가 감지 → 자동 배포
                                   └ 앱 Pod → host.docker.internal:11434 (Mac의 Ollama, GPU 사용)
```

| 경로 | 역할 |
|---|---|
| `Dockerfile`, `docker/start.sh` | 이미지 하나로 UI(기본)와 API 실행. 시작 시 가상 데이터 시드, non-root |
| `requirements.lock` | 이미지용 고정 의존성 |
| `.github/workflows/ci.yml` | CI/CD. 액션은 커밋 SHA로 고정, 잡별 최소 권한 |
| `k8s/` | Kustomize 매니페스트 (ClusterIP만, read-only 루트 파일시스템) |
| `argocd/application.yaml` | Argo CD 자동 동기화 설정 |

```bash
# 로컬 이미지 확인
docker build -t settlement-assistant .
docker run --rm -p 8501:8501 -e LLM_PROVIDER=ollama -e OLLAMA_HOST=http://host.docker.internal:11434 settlement-assistant

# 클러스터 접속
kubectl -n settlement port-forward svc/settlement-ui 8501:8501
```

## 보안 메모

- 비밀값은 저장소·이미지에 넣지 않는다 (`.gitignore`, `.dockerignore`). 현재 배포는 API 키를 쓰지 않는다.
- API에는 인증이 없으므로 ClusterIP로만 두고 port-forward로 접근한다. Ollama도 `127.0.0.1`에만 열어 두고 `0.0.0.0`으로 바꾸지 않는다.
- LLM 출력의 마크다운 이미지는 무력화한다 (`markdown_safety.py`). 계약 메모 등에 섞인 프롬프트 인젝션이 이미지 URL로 데이터를 내보내는 경로를 막기 위함이다. 도구는 모두 읽기 전용이다.
- 입력 길이를 1,000자로 제한한다.
