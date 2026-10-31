FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY notif_worker ./notif_worker
CMD ["python", "-m", "notif_worker.worker"]
