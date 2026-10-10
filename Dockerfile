FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --default-timeout=600 --retries 10 --timeout 60 -r requirements.txt

COPY app/ ./app/
COPY config/ ./config/

RUN mkdir -p /app/data/input /app/data/output /app/data/templates /app/data/dictionaries /app/config

ENV PYTHONUNBUFFERED=1

EXPOSE 8001

CMD ["gunicorn", "-b", "0.0.0.0:8001", "-w", "1", "--timeout", "600", "app.api.__main__:app"]