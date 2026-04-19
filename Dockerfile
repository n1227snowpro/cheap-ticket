FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# CJK fonts for card image generation
RUN apt-get update && apt-get install -y fonts-noto-cjk && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

ENV CHEAPTICKET_DATA=/app/data

EXPOSE 9002

CMD ["python3", "app.py"]
