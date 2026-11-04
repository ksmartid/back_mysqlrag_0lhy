# ---------- 1단계: uv.lock 기준으로 의존성 설치 ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---------- 2단계: FastAPI 실행 ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul \
    PATH="/app/.venv/bin:$PATH" \
    KOREAN_FONT_PATH=/usr/share/fonts/truetype/nanum/NanumGothic.ttf

RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-nanum tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /app/.venv /app/.venv
COPY --chown=appuser:appuser app/ ./app/
COPY --chown=appuser:appuser data/ ./data/

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).close()"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
