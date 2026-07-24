FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-cache --no-dev

COPY mqttmcpserver.py .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV HOME=/app

RUN groupadd --system mcpuser && useradd --system --no-create-home --shell /bin/false --gid mcpuser mcpuser \
    && chown -R mcpuser:mcpuser /app
USER mcpuser

ENTRYPOINT ["uv", "run", "mqttmcpserver.py"]
