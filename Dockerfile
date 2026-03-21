FROM python:3.11-slim

# Installer Chromium + dépendances
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       chromium chromium-driver \
       fonts-liberation \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Variables pour que Selenium trouve Chromium
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Render injecte la variable PORT
ENV PORT=5000

EXPOSE ${PORT}

CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 300 "webapp:app"
