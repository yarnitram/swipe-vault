FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd -g 10001 swipevault && \
    useradd -u 10001 -g 10001 -m -s /usr/sbin/nologin swipevault && \
    mkdir -p /app /data/assets && \
    chown -R swipevault:swipevault /app /data

WORKDIR /app

COPY pyproject.toml /app/pyproject.toml
COPY app /app/app
COPY alembic.ini /app/alembic.ini
COPY alembic /app/alembic

RUN pip install --upgrade pip && \
    pip install ".[dev]"

COPY tests /app/tests

USER swipevault:swipevault

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
