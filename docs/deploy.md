redis-server /opt/homebrew/etc/redis.conf
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload


## 🚀 Деплой без Docker

### Что нужно установить на сервер

```
Ubuntu 22.04 / 24.04
Python 3.11+
Node.js 20+
PostgreSQL 16
Redis 7
```

---

### 1. Базовые пакеты

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip \
  nodejs npm postgresql redis-server nginx git curl
```

---

### 2. PostgreSQL

```bash
sudo systemctl start postgresql
sudo -u postgres psql <<EOF
CREATE USER const WITH PASSWORD 'const555';
CREATE DATABASE const OWNER const;
EOF
```

---

### 3. Redis

```bash
sudo systemctl enable --now redis-server
redis-cli ping  # должен ответить PONG
```

---

### 4. Бэкенд (FastAPI)

cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload


# Виртуальное окружение
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Настроить .env
cp .env.example .env
nano .env
```

В `.env` заменить:
```env
DATABASE_URL=postgresql+asyncpg://construction_user:your_strong_password@localhost:5432/construction
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CORS_ORIGINS=["https://yourdomain.com"]
```

```bash
# Применить миграции
alembic upgrade head
```

---

### 5. Systemd — 3 сервиса

**`/etc/systemd/system/construction-api.service`**
```ini
[Unit]
Description=Construction FastAPI
After=postgresql.service redis.service

[Service]
User=www-data
WorkingDirectory=/srv/app/backend
EnvironmentFile=/srv/app/backend/.env
ExecStart=/srv/app/backend/venv/bin/python scripts/run_with_weekly_logs.py \
          --log-dir /srv/app/backend/logs --log-name api -- \
          /srv/app/backend/venv/bin/python -m app.run_api
Restart=always

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/construction-worker.service`**
```ini
[Unit]
Description=Construction Celery Worker
After=redis.service

[Service]
User=www-data
WorkingDirectory=/srv/app/backend
EnvironmentFile=/srv/app/backend/.env
ExecStart=/srv/app/backend/venv/bin/python scripts/run_with_weekly_logs.py \
          --log-dir /srv/app/backend/logs --log-name celery-worker -- \
          /srv/app/backend/venv/bin/celery -A app.tasks.celery_app.celery_app \
          worker --loglevel=info --concurrency=4
Restart=always

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/construction-beat.service`**
```ini
[Unit]
Description=Construction Celery Beat
After=redis.service

[Service]
User=www-data
WorkingDirectory=/srv/app/backend
EnvironmentFile=/srv/app/backend/.env
ExecStart=/srv/app/backend/venv/bin/python scripts/run_with_weekly_logs.py \
          --log-dir /srv/app/backend/logs --log-name celery-beat -- \
          /srv/app/backend/venv/bin/celery -A app.tasks.celery_app.celery_app \
          beat --loglevel=info
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now construction-api construction-worker construction-beat
```

---

### 6. Фронтенд (Next.js)

```bash
cd /srv/app/frontend

# .env.local
echo "NEXT_PUBLIC_API_URL=https://yourdomain.com" > .env.local

npm install
npm run build
```

**`/etc/systemd/system/construction-front.service`**
```ini
[Unit]
Description=Construction Next.js
After=network.target

[Service]
User=www-data
WorkingDirectory=/srv/app/frontend
ExecStart=/usr/bin/npm run start
Environment=PORT=3000
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now construction-front
```

---

### 7. Nginx (reverse proxy)

```nginx
# /etc/nginx/sites-available/construction
server {
    listen 80;
    server_name yourdomain.com;

    # Frontend
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # API
    location /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/construction /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# SSL (Let's Encrypt)
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d yourdomain.com
```

---

### 8. Проверка

```bash
sudo systemctl status construction-api construction-worker construction-beat construction-front

# Логи
journalctl -u construction-api -f
```

Недельные файлы логов будут появляться в `/srv/app/backend/logs` и `/srv/app/frontend/logs`.

| Сервис | Адрес |
|--------|-------|
| Фронтенд | `https://yourdomain.com` |
| API docs | `https://yourdomain.com/api/docs` |

---

> **Совет**: если нужен быстрый старт без своего сервера — **Railway.app** или **Render.com** поднимают FastAPI + PostgreSQL + Redis по `requirements.txt` без единой строки Docker-конфига. Скажи, если хочешь разобрать этот вариант.
