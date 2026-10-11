FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    SETTLEMENT_DB_PATH=/app/data/settlement.db \
    HOME=/tmp

WORKDIR /app

# 의존성 레이어를 먼저 두어 코드만 바뀔 때 캐시를 재사용한다
COPY requirements.lock .
RUN pip install -r requirements.lock

COPY pyproject.toml .
COPY src ./src
RUN pip install --no-deps .

COPY api ./api
COPY ui ./ui
COPY --chmod=0755 docker/start.sh /usr/local/bin/start.sh

# root가 아닌 사용자로 실행
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /app/data && chown app /app/data
USER 10001

EXPOSE 8501 8000
ENTRYPOINT ["start.sh"]
CMD ["streamlit", "run", "ui/streamlit_app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
