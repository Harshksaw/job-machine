FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Node.js runtime + Claude Code CLI — the service shells out to `claude -p`
# for its one LLM call (see app/claude_cli.py), so the CLI must be present
# in the image. Requires the container to have Claude Code auth available
# at runtime (see docker-compose.yml's ~/.claude volume mount).
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g @anthropic-ai/claude-code

RUN pip install --no-cache-dir uv

WORKDIR /srv/app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY content ./content
COPY templates ./templates

RUN mkdir -p /srv/app/output

EXPOSE 8420

CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8420"]
