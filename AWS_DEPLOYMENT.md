# Deploy Assessment Engine on AWS (Free Tier)

This guide deploys the app on a single **EC2** instance **without Docker**. Use **MongoDB Atlas** (free) for the database and run the backend with **Gunicorn** and the frontend as static files behind **Nginx**.

---

## Current project layout (no Docker)

```
Assessment Engine/
├── backend/                 # Flask + Celery (optional)
│   ├── app/
│   ├── requirements.txt
│   ├── wsgi.py
│   └── .env                 # optional; .env at project root is used too
├── frontend/                # Vite + React
│   ├── src/
│   ├── dist/                # created by npm run build (deploy this)
│   └── package.json
├── deploy/
│   └── deploy.sh           # builds frontend for production
├── .env                     # production env (create from .env.production.example)
├── .env.production.example
└── AWS_DEPLOYMENT.md        # this file
```

Backend reads `.env` from **project root** or `backend/.env`. Frontend is built to `frontend/dist` and served by Nginx.

---

## Quick deploy checklist

| Step | Where | Action |
|------|--------|--------|
| 1 | MongoDB Atlas | Create cluster, user, allow `0.0.0.0/0` (or EC2 IP), get URI: `.../aae_db?retryWrites=...` |
| 2 | AWS EC2 | Launch Ubuntu 22.04, open 22 (SSH), 80 (HTTP), 443 (HTTPS optional) |
| 3 | EC2 | Install Python 3.12, Node 20, nginx, **Redis** |
| 4 | Local | Build frontend: `cd frontend && npm ci && npm run build`; push to Git or SCP to EC2 |
| 5 | EC2 | Copy `.env.production.example` to `.env` at **project root**, set `SECRET_KEY`, `MONGO_URI`, `OPENAI_API_KEY`, `STORAGE_PROVIDER=local`, `LOCAL_STORAGE_PATH`; keep `USE_CELERY_REDIS=true` and Redis URLs |
| 6 | EC2 | Run backend (gunicorn), **Celery workers** (OCR + evaluation; OCR worker also runs **exam creation** on `default` queue), serve frontend with nginx |
| 7 | EC2 | Ensure **upload dir** is writable so exam creation can store job files (`/var/lib/aae/uploads` or fallback to `/tmp`) |
| 8 | Browser | Open `http://YOUR_EC2_PUBLIC_IP` |

---

## Commands: Local vs Server

Use these in order. Replace `YOUR_EC2_PUBLIC_IP`, `your-key.pem`, and paths as needed.

### On your local machine

**1. Build frontend (required for UI changes: exam upload, job status, cancel):**

```bash
cd "/path/to/Assessment Engine/frontend"
npm ci
npm run build
```

**2a. Push code to Git (so server can pull):**

```bash
cd "/path/to/Assessment Engine"
git add .
git commit -m "Deploy exam creation and updates"
git push origin main
```

**2b. Or copy project to server via SCP (no Git):**

```bash
scp -i your-key.pem -r "/path/to/Assessment Engine" ubuntu@YOUR_EC2_PUBLIC_IP:~/assessment-engine
```

---

### On the server (EC2) — first-time setup

**1. SSH in:**

```bash
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

**2. Install dependencies (once per instance):**

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm nginx redis-server git
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

**3. Get the code (if using Git):**

```bash
cd ~
git clone https://github.com/YOUR_USERNAME/assessment-engine.git
cd assessment-engine
```

If you used SCP, the project is already at `~/assessment-engine`; just `cd ~/assessment-engine`.

**4. Create and edit `.env` at project root:**

```bash
cd ~/assessment-engine
cp .env.production.example .env
nano .env
```

Set at least: `SECRET_KEY`, `MONGO_URI`, `OPENAI_API_KEY`, `USE_CELERY_REDIS=true`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `STORAGE_PROVIDER=local`, `LOCAL_STORAGE_PATH=/var/lib/aae/uploads`. Save (Ctrl+X, Y, Enter).

**5. Create upload directory (for scripts and exam jobs):**

```bash
sudo mkdir -p /var/lib/aae/uploads
sudo chown ubuntu:ubuntu /var/lib/aae/uploads
```

**6. Backend venv and install:**

```bash
cd ~/assessment-engine/backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn
deactivate
```

**7. Build frontend:**

```bash
cd ~/assessment-engine/frontend
npm ci
npm run build
cd ..
```

**8. Create systemd service files** (see Step 6 and Step 6b in this doc for full contents):

- `/etc/systemd/system/aae-backend.service` — Gunicorn, `--timeout 300`
- `/etc/systemd/system/aae-celery-ocr.service` — `-Q ocr,default`
- `/etc/systemd/system/aae-celery-evaluation.service` — `-Q evaluation`

Use `EnvironmentFile=/home/ubuntu/assessment-engine/.env` in each.

**9. Enable and start services:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable aae-backend aae-celery-ocr aae-celery-evaluation
sudo systemctl start aae-backend aae-celery-ocr aae-celery-evaluation
sudo systemctl status aae-backend aae-celery-ocr aae-celery-evaluation
```

**10. Configure Nginx** (see Step 7), then:

```bash
sudo ln -sf /etc/nginx/sites-available/aae /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

---

### On the server (EC2) — every time you deploy new code

Run these after you push to Git (or re-copy via SCP):

```bash
cd ~/assessment-engine

# Get latest code (if using Git)
git pull

# Rebuild frontend
cd frontend && npm ci && npm run build && cd ..

# Restart app and workers
sudo systemctl restart aae-backend aae-celery-ocr aae-celery-evaluation
```

**Check that services are up:**

```bash
sudo systemctl status aae-backend aae-celery-ocr aae-celery-evaluation
```

**View logs if something fails:**

```bash
sudo journalctl -u aae-backend -n 80 --no-pager
sudo journalctl -u aae-celery-ocr -n 80 --no-pager
sudo journalctl -u aae-celery-evaluation -n 80 --no-pager
```

**Quick check Redis:**

```bash
redis-cli ping
# should reply: PONG
```

---

## Prerequisites

- AWS account with free credits
- MongoDB Atlas account (free): [cloud.mongodb.com](https://cloud.mongodb.com)
- OpenAI API key
- Git (to clone or push code)

---

## Step 1: Create MongoDB Atlas Cluster

1. Go to [cloud.mongodb.com](https://cloud.mongodb.com) → Create free cluster
2. Choose a region (e.g. `us-east-1`)
3. Create a database user (save username + password)
4. **Network Access** → Add IP: `0.0.0.0/0` (allow from anywhere; restrict later with your EC2 IP)
5. Copy the connection string, e.g.:
   ```
   mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
6. Add database name: `mongodb+srv://...mongodb.net/aae_db?retryWrites=true&w=majority`

---

## Step 2: Launch EC2 Instance

1. AWS Console → EC2 → **Launch Instance**
2. **Name:** `assessment-engine`
3. **AMI:** Ubuntu 22.04 LTS
4. **Instance type:** `t3.small` (2 vCPU, 2GB RAM) — or `t2.micro` (1GB) if you accept slower startup
5. **Key pair:** Create new or select existing (download `.pem`)
6. **Security group:**
   - SSH (22) from your IP
   - HTTP (80) from 0.0.0.0/0
   - HTTPS (443) from 0.0.0.0/0 (optional for SSL)
7. **Storage:** 20 GB
8. Launch

---

## Step 3: Connect and Install Dependencies

SSH into the instance:

```bash
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

Install Python 3.12, Node 20, nginx, Redis, and gunicorn:

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip nodejs npm nginx redis-server

# Install Node 20 (if Ubuntu ships older version)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs

sudo apt install -y git
sudo systemctl enable redis-server
sudo systemctl start redis-server
```

---

## Step 4: Clone Project and Build Frontend

**Option A: Push to GitHub and clone on EC2**

On your local machine:

```bash
cd "/path/to/Assessment Engine"
git init && git add . && git commit -m "Deploy"
git remote add origin https://github.com/YOUR_USERNAME/assessment-engine.git
git push -u origin main
```

On EC2:

```bash
git clone https://github.com/YOUR_USERNAME/assessment-engine.git
cd assessment-engine
```

**Option B: SCP the project to EC2**

```bash
scp -i your-key.pem -r "/path/to/Assessment Engine" ubuntu@YOUR_EC2_IP:~/assessment-engine
```

On EC2:

```bash
cd ~/assessment-engine
```

Build frontend:

```bash
cd frontend
npm ci
npm run build
cd ..
# Output: frontend/dist/
```

---

## Step 5: Configure Environment

On EC2:

```bash
cd ~/assessment-engine

# Copy example env
cp .env.production.example .env

# Edit with your values
nano .env
```

Set (production with Redis + Celery):

```
SECRET_KEY=<run: openssl rand -hex 32>
MONGO_URI=mongodb+srv://USER:PASS@cluster.xxx.mongodb.net/aae_db?retryWrites=true&w=majority
OPENAI_API_KEY=sk-...
JWT_SECRET_KEY=<same as SECRET_KEY or leave empty>
ENVIRONMENT=production
DEBUG=false
USE_CELERY_REDIS=true
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/1
CELERY_RESULT_BACKEND=redis://localhost:6379/2
STORAGE_PROVIDER=local
LOCAL_STORAGE_PATH=/var/lib/aae/uploads
LOG_LEVEL=INFO
```

Optional: `OPENAI_MODEL=gpt-4o-mini`, `OPENAI_MODEL_VISION=gpt-4o` (defaults). To run without Celery, set `USE_CELERY_REDIS=false` (sync mode).

Create uploads dir (used for script uploads and exam job files):

```bash
sudo mkdir -p /var/lib/aae/uploads
sudo chown ubuntu:ubuntu /var/lib/aae/uploads
```

Optional: create `exam_jobs` under uploads so async exam creation stores files there (otherwise the app falls back to `/tmp/aae_exam_jobs`):

```bash
mkdir -p /var/lib/aae/uploads/exam_jobs
# ubuntu already owns /var/lib/aae/uploads, so exam_jobs is writable
```

Save and exit (Ctrl+X, Y, Enter).

---

## Step 6: Set Up Backend (gunicorn)

On EC2:

```bash
cd ~/assessment-engine/backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt gunicorn
```

Create a systemd service so the backend runs on boot:

```bash
sudo nano /etc/systemd/system/aae-backend.service
```

Content:

```ini
[Unit]
Description=Assessment Engine Backend
After=network.target

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/assessment-engine/backend
Environment="PATH=/home/ubuntu/assessment-engine/backend/venv/bin"
ExecStart=/home/ubuntu/assessment-engine/backend/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 --timeout 300 wsgi:app
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aae-backend
sudo systemctl start aae-backend
sudo systemctl status aae-backend
```

---

## Step 6b: Set Up Celery Workers (Redis)

Production uses two Celery workers: one for OCR, one for evaluation. Create two systemd services.

**OCR worker** (ingest, PDF split, page OCR, aggregate, segment):

```bash
sudo nano /etc/systemd/system/aae-celery-ocr.service
```

```ini
[Unit]
Description=Assessment Engine Celery OCR Worker
After=network.target redis-server.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/assessment-engine/backend
Environment="PATH=/home/ubuntu/assessment-engine/backend/venv/bin"
EnvironmentFile=/home/ubuntu/assessment-engine/.env
ExecStart=/home/ubuntu/assessment-engine/backend/venv/bin/celery -A celery_app.celery worker -Q ocr,default -l info --concurrency=4
Restart=always

[Install]
WantedBy=multi-user.target
```

**Evaluation worker** (prepare_script, evaluate_question):

```bash
sudo nano /etc/systemd/system/aae-celery-evaluation.service
```

```ini
[Unit]
Description=Assessment Engine Celery Evaluation Worker
After=network.target redis-server.service

[Service]
User=ubuntu
Group=ubuntu
WorkingDirectory=/home/ubuntu/assessment-engine/backend
Environment="PATH=/home/ubuntu/assessment-engine/backend/venv/bin"
EnvironmentFile=/home/ubuntu/assessment-engine/.env
ExecStart=/home/ubuntu/assessment-engine/backend/venv/bin/celery -A celery_app.celery worker -Q evaluation -l info --concurrency=4
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start both:

```bash
sudo systemctl daemon-reload
sudo systemctl enable aae-celery-ocr aae-celery-evaluation
sudo systemctl start aae-celery-ocr aae-celery-evaluation
sudo systemctl status aae-celery-ocr aae-celery-evaluation
```

If your `.env` is not at project root or systemd does not load it, add explicit `Environment="KEY=value"` lines. **Important:** In systemd, `%` is special. If you set `MONGO_URI` in the unit file, escape `%` as `%%` (e.g. `mako%%401731` instead of `mako%401731`). Otherwise you get "Failed to resolve specifiers in MONGO_URI ... Invalid slot".

---

## Step 7: Configure Nginx

```bash
sudo nano /etc/nginx/sites-available/aae
```

Content:

```nginx
server {
    listen 80 default_server;
    server_name _;

    root /home/ubuntu/assessment-engine/frontend/dist;
    index index.html;
    try_files $uri $uri/ /index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 50M;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }

    location /api/docs/ {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
    }
}
```

Enable and reload:

```bash
sudo ln -sf /etc/nginx/sites-available/aae /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

---

## Step 8: Access Your App

Open in a browser:

```
http://YOUR_EC2_PUBLIC_IP
```

Create an account via Sign Up and start using the app.

---

## Deploying exam creation (async) on AWS

Async exam creation (upload → 202 + jobId → poll until COMPLETE, with optional cancel) requires the same stack as OCR/evaluation plus writable storage for job files. Follow the steps below so **all exam creation features work** on AWS.

### 1. Prerequisites already in place

- **Redis** running (`redis-server`), used as Celery broker.
- **Backend** (Gunicorn) and **Celery workers** (OCR + evaluation) running via systemd.
- **`.env`** at project root with `USE_CELERY_REDIS=true`, Redis URLs, `LOCAL_STORAGE_PATH`, and `OPENAI_API_KEY`.

### 2. How exam creation runs

- When a user uploads an exam (question paper ± rubric), the API saves files under a job directory and enqueues a **Celery task** `create_exam_from_upload_task`.
- This task is routed to the **default** queue. The **OCR worker** is started with `-Q ocr,default`, so it runs both OCR tasks and **exam creation tasks**. No extra worker or queue is needed.
- The task reads files from the job dir, calls OpenAI (exam extraction ± rubric generation), creates the exam in MongoDB, and updates the job status to `COMPLETE` or `FAILED`.

### 3. Storage for exam job files

- Job files are stored under `LOCAL_STORAGE_PATH/exam_jobs/<job_id>/`. If that path is not writable (e.g. permission denied), the app falls back to `$TMPDIR/aae_exam_jobs` (e.g. `/tmp/aae_exam_jobs`).
- For a clean setup on EC2, use the same uploads dir as for scripts:
  - `LOCAL_STORAGE_PATH=/var/lib/aae/uploads`
  - Create and own the dir (see Step 5): `sudo mkdir -p /var/lib/aae/uploads && sudo chown ubuntu:ubuntu /var/lib/aae/uploads`
  - Optionally: `mkdir -p /var/lib/aae/uploads/exam_jobs` (not required; the app creates it if writable).

### 4. Environment variables (exam-related)

In `.env` at project root, ensure:

| Variable | Purpose |
|----------|--------|
| `USE_CELERY_REDIS=true` | Enables async exam creation (returns 202 + jobId instead of blocking). |
| `LOCAL_STORAGE_PATH=/var/lib/aae/uploads` | Base path for uploads and exam job dirs (must be writable by the app user). |
| `OPENAI_API_KEY=sk-...` | Required for exam extraction and optional rubric generation. |
| `OPENAI_MODEL_EXAM_EXTRACTION` | (Optional) Model for exam extraction; default `gpt-4o-mini`. |
| `USE_AUTO_RUBRIC_GENERATION` | (Optional) Default for “generate rubrics” when no rubric file; default `true`. |

Backend and Celery workers read `.env` via `EnvironmentFile=/home/ubuntu/assessment-engine/.env` in systemd. If you set variables in the unit file, remember to escape `%` as `%%` in `MONGO_URI`.

### 5. Celery workers (OCR = exam + OCR)

- **OCR worker** must listen to the **default** queue so exam tasks run. The doc’s OCR worker is already correct:
  - `ExecStart=... celery -A celery_app.celery worker -Q ocr,default -l info --concurrency=4`
- **Evaluation worker** only needs the `evaluation` queue.
- After changing `.env` or code, restart so all services see the same config:
  ```bash
  sudo systemctl restart aae-backend aae-celery-ocr aae-celery-evaluation
  ```

### 6. Timeouts (already in doc)

- **Gunicorn:** `--timeout 300` so long sync requests don’t die early.
- **Nginx** `location /api/`: `proxy_connect_timeout 300s; proxy_send_timeout 300s; proxy_read_timeout 300s;` so upload and long-running API calls don’t get 504.

### 7. Deploying code changes (exams + rest)

When you pull new code (including exam creation, cancel job, or frontend polling):

```bash
cd ~/assessment-engine
git pull

# Rebuild frontend (exam upload UI, job status, cancel button)
cd frontend && npm ci && npm run build && cd ..

# Restart backend and both Celery workers (OCR runs exam tasks)
sudo systemctl restart aae-backend aae-celery-ocr aae-celery-evaluation
```

### 8. Verify exam creation

1. Open the app in the browser and sign in.
2. Go to **Exams** and upload a question paper (PDF/DOCX/image).
3. You should get a **202** response and see “Creating exam…” with a **Cancel** option.
4. Polling should move the job to **COMPLETE** and show the new exam, or **FAILED** with an error.
5. Check backend logs: `sudo journalctl -u aae-backend -n 50 --no-pager`
6. Check OCR worker (runs exam tasks): `sudo journalctl -u aae-celery-ocr -n 50 --no-pager`

If the job stays in CREATING or fails, check: Redis running (`redis-cli ping`), `USE_CELERY_REDIS=true`, OCR worker running and listening on `ocr,default`, and `LOCAL_STORAGE_PATH` (or fallback) writable.

---

## Optional: Domain + HTTPS

1. Point a domain to your EC2 public IP
2. Install Certbot for Let's Encrypt:

   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d yourdomain.com
   ```

3. Certbot will update the Nginx config for HTTPS.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| 504 Gateway Timeout on upload/exam | Nginx proxy timeout is too short. In `location /api/` add `proxy_read_timeout 300s;` (and `proxy_connect_timeout` / `proxy_send_timeout` if needed), then `sudo nginx -t` and `sudo systemctl reload nginx`. |
| "Failed to resolve specifiers in MONGO_URI ... Invalid slot" | In Celery (or backend) systemd unit, `MONGO_URI` contains `%` (e.g. `%40`). In systemd, escape it as `%%` — e.g. `mako%%401731` instead of `mako%401731`. Then `sudo systemctl daemon-reload` and restart the service. |
| 502 Bad Gateway | `sudo systemctl status aae-backend` — check Flask is up; `sudo journalctl -u aae-backend -f` for logs |
| MongoDB connection failed | Verify Atlas IP allowlist includes EC2 IP or `0.0.0.0/0` |
| Out of memory | Use `t3.small` or larger; ensure MongoDB Atlas is used (not local Mongo) |

---

## Update Deployment

Run on EC2 when you deploy new code (including exam creation, frontend job polling, cancel):

```bash
cd ~/assessment-engine
git pull
cd frontend && npm ci && npm run build && cd ..
sudo systemctl restart aae-backend aae-celery-ocr aae-celery-evaluation
```

For full exam-creation setup (storage, env, workers), see **Deploying exam creation (async) on AWS** above.

---

## Summary

| Component     | On AWS                                                    |
|--------------|------------------------------------------------------------|
| App server   | Single EC2 (Ubuntu 22.04)                                 |
| Database     | MongoDB Atlas (free tier)                                  |
| Backend      | Gunicorn (Flask), no Docker                                |
| Queue        | Redis on EC2 (Celery broker)                               |
| Workers      | Celery OCR (ocr + **default** for exam creation) + Evaluation (systemd) |
| Frontend     | Nginx serving `frontend/dist`                              |
| Config       | `.env` at project root, `USE_CELERY_REDIS=true`, writable `LOCAL_STORAGE_PATH` |
