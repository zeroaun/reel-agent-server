FROM python:3.11-slim

# Installe FFmpeg + libass pour les sous-titres
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libass9 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "2", "app:app"]
