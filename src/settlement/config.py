import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")  # anthropic / ollama

CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = os.getenv("CLAUDE_EFFORT", "medium")

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
# Ollama 기본 컨텍스트(4096)는 프롬프트+도구 정의+멀티턴 이력을 담기에 부족해 앞부분이 잘린다
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))

DB_PATH = Path(os.getenv("SETTLEMENT_DB_PATH", PROJECT_ROOT / "data" / "settlement.db"))
