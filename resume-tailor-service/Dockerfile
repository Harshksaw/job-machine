FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-extra \
    texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/*

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
