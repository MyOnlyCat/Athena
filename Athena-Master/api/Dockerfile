FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system athena && useradd --system --gid athena athena

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

RUN mkdir -p /data && chown -R athena:athena /app /data

USER athena

EXPOSE 8001

CMD ["sh", "-c", "python -m alembic upgrade head && exec python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8001 --workers 1"]
