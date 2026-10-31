FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY tracemind ./tracemind
COPY migrations ./migrations
RUN pip install --no-cache-dir -e . && pip install --no-cache-dir graphifyy
ENV TRACEMIND_MIGRATIONS_DIR=/app/migrations
EXPOSE 8100
CMD ["uvicorn", "tracemind.main:app", "--host", "0.0.0.0", "--port", "8100"]
