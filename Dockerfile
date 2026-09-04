FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y tesseract-ocr && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY . .

CMD ["python", "app.py"]