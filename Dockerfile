FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY sheets_search_mcp/ sheets_search_mcp/
COPY FRAMING.md .

CMD ["uv", "run", "python", "-m", "sheets_search_mcp.bot"]
