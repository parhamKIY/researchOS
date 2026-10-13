FROM python:3.11-slim-bookworm AS base
RUN python -m pip install --no-cache-dir uv==0.12.2
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PYTHONPATH="/app/src"
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --create-home --uid 10001 researchos && mkdir /app/storage && chown researchos:researchos /app/storage
FROM base AS test
RUN uv sync --frozen --group dev --no-install-project
COPY tests ./tests
USER researchos
CMD ["pytest", "-p", "no:cacheprovider"]

FROM base AS runtime
USER researchos
CMD ["uvicorn", "researchos.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
