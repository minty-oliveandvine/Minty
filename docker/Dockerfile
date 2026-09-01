FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      build-essential \
      gcc \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

RUN python -m venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --active --frozen --no-dev --no-default-groups --no-install-project

COPY . .
COPY docker/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# `sed` strips CRLF so the script still runs when the repo is checked out on
# Windows with autocrlf.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && \
    chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 5001

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["gunicorn", "-w", "4", "--max-requests", "200", "--max-requests-jitter", "50", "-b", "0.0.0.0:5001", "main:app"]
