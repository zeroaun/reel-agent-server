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

# Validate that app.py is present and importable before finalising the image.
# This turns a silent runtime failure into a loud build-time failure, and
# busts any stale layer cache that may have been left by a prior commit where
# app.py was deleted.
RUN python -c "import py_compile, sys; py_compile.compile('app.py', doraise=True); print('app.py OK')"

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "300", "--workers", "2", "app:app"]
