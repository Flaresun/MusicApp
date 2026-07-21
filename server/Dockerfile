FROM python:3.12-slim

# Install uv by copying it directly from the official Astral image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Enable bytecode compilation and copy files
ENV UV_COMPILE_BYTECODE=1

# Copy project dependency files first for better layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies (without installing the root package yet)
RUN uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application source code
COPY . .

# Build/sync the project root
RUN uv sync --frozen --no-dev

# Place virtualenv executables at the front of PATH
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src

# Expose port 8000
EXPOSE 8000

# Run uvicorn directly (no need to specify full path to .venv/bin)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]