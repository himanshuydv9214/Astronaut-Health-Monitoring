# ARES - offline, single-container deployment of the onboard service + dashboard.
# Build:  docker build -t ares .
# Run:    docker run --rm -p 8000:8000 ares        -> http://localhost:8000
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OMP_NUM_THREADS=1 ARES_HOST=0.0.0.0 ARES_PORT=8000 ARES_SPEED=2
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ares ./ares
COPY knowledge_base ./knowledge_base
COPY models ./models
COPY scripts ./scripts
COPY tests ./tests
COPY pytest.ini ./
RUN mkdir -p data/cache data/external
EXPOSE 8000
# No network access is required at runtime (onboard / offline-first).
CMD ["python", "-m", "ares.api.server"]
