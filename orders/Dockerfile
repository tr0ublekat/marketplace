FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

CMD ["uvicorn", "app.main:app", "--workers", "4", "--host", "0.0.0.0", "--port", "8000"]