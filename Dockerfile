# Autonomous QA Testing Agent — Docker (optional; local verification comes first)
FROM python:3.12-slim

WORKDIR /app

# System dependencies for Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
        libgbm1 libgtk-3-0 libpango-1.0-0 libxss1 libxcomposite1 \
        libxdamage1 libxfixes1 libxrandr2 libasound2 libxkbcommon0 \
        ca-certificates fonts-liberation wget \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app
COPY demo-app ./demo-app

RUN pip install --no-cache-dir -e . && \
    playwright install chromium && \
    playwright install-deps chromium

ENV QA_HOST=0.0.0.0 \
    QA_PORT=8000 \
    QA_LLM_MODE=disabled \
    QA_HEADLESS=true

EXPOSE 8000

# Note: this image runs the agent backend only. Bring your own demo target or
# set QA_ALLOWED_HOSTS to an explicitly authorized application.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
