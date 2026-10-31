FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY notif_api ./notif_api
CMD ["uvicorn", "notif_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
