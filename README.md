# 📖 Low-Content Book Generator

A simple web app that takes a **single page image (JPG or PNG)** and duplicates it N times to generate a ready-to-publish **PDF file** — perfect for KDP low-content books like journals, notebooks, planners, and log books.

---

## ✨ Features

- Upload any JPG or PNG page template
- Set the number of pages (1–1000, default: 100)
- Custom output filename support
- Drag-and-drop file upload
- One-click PDF download
- Clean, modern web UI

---

## 🗂 Project Structure

```
low-content-book-generator/
├── app.py                    # Flask web server (Web UI backend)
├── low_content_generator.py  # Standalone CLI version
├── templates/
│   └── index.html            # Web UI frontend
├── requirements.txt          # Python dependencies
└── README.md
```

---

## 🖥 Local Development

### 1. Clone the repo

```bash
git clone https://github.com/n1227snowpro/low-content-book-generator.git
cd low-content-book-generator
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
python3 app.py
```

Open your browser at **http://localhost:9000**

---

## 🖱 CLI Usage (without the web UI)

```bash
# Default 100 pages
python3 low_content_generator.py page.jpg

# Custom page count
python3 low_content_generator.py page.png --pages 50

# Custom output filename
python3 low_content_generator.py page.jpg --pages 120 --output my_journal.pdf
```

---

## 🚀 Server Deployment Guide

### Requirements

- Ubuntu 20.04+ / Debian / CentOS (or any Linux VPS)
- Python 3.9+
- Nginx (recommended as reverse proxy)
- `gunicorn` (production WSGI server)

---

### Step 1 — SSH into your server

```bash
ssh user@your-server-ip
```

---

### Step 2 — Install system dependencies

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip python3-venv nginx -y
```

---

### Step 3 — Clone the project

```bash
cd /var/www
sudo git clone https://github.com/n1227snowpro/low-content-book-generator.git
sudo chown -R $USER:$USER /var/www/low-content-book-generator
cd /var/www/low-content-book-generator
```

---

### Step 4 — Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

---

### Step 5 — Test with Gunicorn

```bash
gunicorn --bind 0.0.0.0:9000 app:app
```

Visit `http://your-server-ip:9000` to confirm it works, then press `Ctrl+C`.

---

### Step 6 — Create a systemd service

```bash
sudo nano /etc/systemd/system/lowcontent.service
```

Paste the following (replace `your_username` with your actual Linux user):

```ini
[Unit]
Description=Low-Content Book Generator
After=network.target

[Service]
User=your_username
WorkingDirectory=/var/www/low-content-book-generator
ExecStart=/var/www/low-content-book-generator/venv/bin/gunicorn --workers 2 --bind 127.0.0.1:9000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable lowcontent
sudo systemctl start lowcontent
sudo systemctl status lowcontent
```

---

### Step 7 — Configure Nginx reverse proxy

```bash
sudo nano /etc/nginx/sites-available/lowcontent
```

Paste:

```nginx
server {
    listen 80;
    server_name your-domain.com;   # or your server IP

    client_max_body_size 50M;      # allow large image uploads

    location / {
        proxy_pass         http://127.0.0.1:9000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

Enable the site and restart Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/lowcontent /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

---

### Step 8 — (Optional) Enable HTTPS with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d your-domain.com
```

Certbot will automatically update your Nginx config and renew certs.

---

### 🔄 Updating the app on the server

```bash
cd /var/www/low-content-book-generator
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart lowcontent
```

---

## 📦 Requirements

| Package | Purpose |
|---------|---------|
| Flask   | Web framework |
| Pillow  | Image processing & PDF generation |

---

## 📄 License

MIT — free to use and modify.
