FROM python:3.11-slim

# supercronic — Docker-friendly cron daemon (runs the daily scoring job)
ENV SUPERCRONIC_VERSION=0.2.29
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL \
       "https://github.com/aptible/supercronic/releases/download/v${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
       -o /usr/local/bin/supercronic \
    && chmod +x /usr/local/bin/supercronic \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first so this layer caches unless requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Code is volume-mounted at runtime (see docker-compose.yml) so edits on the NAS
# take effect without rebuilding. This COPY is a fallback for standalone runs.
COPY . .

ENV PYTHONUNBUFFERED=1
ENV TZ=America/New_York

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
