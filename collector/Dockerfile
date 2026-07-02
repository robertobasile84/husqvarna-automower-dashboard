# uv-based build. The Astral uv images are multi-arch (amd64 + arm64), and every
# dependency ships pure-Python or prebuilt wheels, so this builds and runs
# anywhere `docker compose` runs.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# UV_COMPILE_BYTECODE speeds up startup; UV_LINK_MODE=copy avoids cache-mount
# warnings; keep uv from trying to manage/download other Pythons in the image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install dependencies first (cached layer) from the lockfile only — reproducible
# and independent of the source, so code changes don't re-resolve deps.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Then the application code.
COPY . ./

# Put the project venv on PATH and run as an unprivileged user.
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --system --uid 10001 app && chown -R app /app
USER app

CMD ["python", "-u", "collector.py"]
