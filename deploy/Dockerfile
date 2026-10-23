# Runtime image for the four step servers, the analyst, and the mock.
# boto3 is included. Azure SDK and SQL Server ODBC are not.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /usr/local/bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY server ./server
COPY tools ./tools
COPY data ./data

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/app \
    AWS_REGION=us-east-1 \
    FNOL_AWS_REGION=us-east-1

RUN uv sync --locked --group aws --no-dev

EXPOSE 8080 8090 8767

# One image. Override the command per service.
CMD ["uv", "run", "--locked", "--group", "aws", "--no-dev", "python", "server/input_server.py", "--http"]
