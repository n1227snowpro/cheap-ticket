FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium

COPY . .

ENV CHEAPTICKET_DATA=/app/data

EXPOSE 9002

CMD ["python3", "app.py"]
