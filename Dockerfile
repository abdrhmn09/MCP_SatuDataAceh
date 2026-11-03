FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_TRANSPORT=sse \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000

WORKDIR /app

COPY pyproject.toml README.md requirements.txt ./
COPY src ./src
COPY data.json ./data.json

RUN python -m pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser
RUN mkdir -p /app/var && chown appuser:appuser /app/var
USER appuser

EXPOSE 8000

CMD ["satu-data-aceh"]
