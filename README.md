# CheapTicket

Scrapes trip.com daily to find the cheapest one-way flights from Taipei (TPE) to 23 popular destinations. Built with Flask + Playwright — no paid APIs.

**Live:** https://flights.srv1213330.hstgr.cloud

---

## Features

- 23 destinations: Japan, Korea, HK, Macau, Thailand, Vietnam, SE Asia, Europe, Americas, Pacific
- Prices in TWD with trip.com affiliate booking links
- Daily auto-scan via Playwright headless Chromium
- Traditional Chinese / English UI toggle
- REST API for programmatic price queries

---

## Run locally

```bash
pip install -r requirements.txt
playwright install chromium
python3 app.py
# → http://localhost:9002
```

---

## Run with Docker

```bash
docker-compose up -d --build
# → http://localhost:9002
```

Data persists in a Docker volume (`cheapticket_data`).

---

## API

### `GET /api/flights`
Returns all cached flight prices as JSON.

### `POST /api/query`
Query the price for a single destination.

**Request:**
```json
{"destination": "Cebu"}
```
Accepts destination name (partial match OK) or IATA code (e.g. `"CEB"`).

**Success (HTTP 200):**
```json
{
  "destination": "Cebu",
  "iata": "CEB",
  "flag": "🇵🇭",
  "region": "SE Asia",
  "price": 5800,
  "currency": "TWD",
  "best_date": "2026-05-10",
  "booking_url": "https://www.trip.com/flights/taipei-to-cebu/...",
  "status": "ok",
  "cached_at": "2026-04-19T10:00:00+00:00",
  "fresh": true
}
```

If the cache is stale the endpoint scrapes live (~30s). If the destination is not found, returns HTTP 404 with an `available` list.

### `POST /api/refresh`
Trigger a full rescan. Optional `?iata=NRT` for a single destination.

---

## Server setup (one-time)

```bash
git clone https://github.com/n1227snowpro/cheap-ticket /opt/cheap-ticket
cd /opt/cheap-ticket
docker-compose up -d --build

# Nginx reverse proxy
cat > /etc/nginx/sites-available/cheapticket << 'EOF'
server {
    listen 80;
    server_name flights.srv1213330.hstgr.cloud;
    location / {
        proxy_pass http://localhost:9002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_buffering off;
    }
}
EOF
ln -s /etc/nginx/sites-available/cheapticket /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
certbot --nginx -d flights.srv1213330.hstgr.cloud
```

## GitHub Actions auto-deploy

Add these secrets in the repo (Settings → Secrets → Actions):

| Secret | Value |
|---|---|
| `SERVER_HOST` | `srv1213330.hstgr.cloud` |
| `SERVER_USER` | `root` |
| `SSH_PRIVATE_KEY` | Your SSH private key |

Every push to `main` auto-deploys to the server via SSH.
