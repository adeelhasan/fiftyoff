# fiftyoff tools image: the same Python + deps on the laptop and the VPS.
# It has no default paid command. Keepa calls only happen via an explicit
# `docker compose run --rm app <script> ...` (CLAUDE.md rule 1).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1

# Deps first so code edits don't reinstall them.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project

COPY . .
RUN uv sync --frozen

RUN useradd --create-home --uid 1000 fiftyoff && chown -R fiftyoff /app
USER fiftyoff

ENTRYPOINT ["uv", "run", "--frozen"]
CMD ["pytest"]
