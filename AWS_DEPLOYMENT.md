# Deploy Assessment Engine on AWS (Free Tier)

This guide deploys the full stack on a single **EC2** instance using Docker Compose. Use **MongoDB Atlas** (free) for the database to stay within free tier limits.

---

## Quick deploy checklist

| Step | Where | Action |
|------|--------|--------|
| 1 | MongoDB Atlas | Create cluster, user, allow `0.0.0.0/0` (or EC2 IP), get URI with DB name: `.../aae_db?retryWrites=...` |
| 2 | AWS EC2 | Launch Ubuntu 22.04, open 22 (SSH), 80 (HTTP), 443 (HTTPS optional) |
| 3 | EC2 | Install Docker + Docker Compose, add user to `docker` group |
| 4 | Local | Build frontend: `cd frontend && npm ci && npm run build`; push to Git or SCP project to EC2 |
| 5 | EC2 | Copy `.env.production.example` to `.env`, set `SECRET_KEY`, `MONGO_URI`, `OPENAI_API_KEY` |
| 6 | EC2 | `docker compose -f docker-compose.production.yml up -d --build` |
| 7 | Browser | Open `http://YOUR_EC2_PUBLIC_IP` |

**To deploy updates later:** on EC2 run `git pull`, rebuild frontend, then `docker compose -f docker-compose.production.yml up -d --build` (or `./deploy/deploy.sh`).

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

## Step 3: Connect and Install Docker

SSH into the instance:

```bash
chmod 400 your-key.pem
ssh -i your-key.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

Install Docker and Docker Compose:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu
newgrp docker
```

---

## Step 4: Clone Project and Build Frontend

On your **local machine**:

```bash
cd "/home/amar-singh/Desktop/Makonis/Projects/Assessment Engine"

# Build React frontend
cd frontend && npm ci && npm run build && cd ..
# Output: frontend/dist/
```

Then either:

**Option A: Push to GitHub and clone on EC2**

```bash
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
scp -i your-key.pem -r "/home/amar-singh/Desktop/Makonis/Projects/Assessment Engine" ubuntu@YOUR_EC2_IP:~/assessment-engine
```

On EC2:

```bash
cd ~/assessment-engine
# If you used SCP and frontend wasn't built, build on EC2:
# cd frontend && npm ci && npm run build && cd ..
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

Set:

```
SECRET_KEY=<run: openssl rand -hex 32>
MONGO_URI=mongodb+srv://USER:PASS@cluster.xxx.mongodb.net/aae_db?retryWrites=true&w=majority
OPENAI_API_KEY=sk-...
JWT_SECRET_KEY=<same as SECRET_KEY or leave empty>
ENVIRONMENT=production
DEBUG=false
```

Save and exit (Ctrl+X, Y, Enter).

---

## Step 6: Deploy with Docker Compose

```bash
cd ~/assessment-engine

# Ensure frontend is built
[ -d frontend/dist ] || (cd frontend && npm ci && npm run build && cd ..)

# Start all services
docker compose -f docker-compose.production.yml up -d --build

# Check status
docker compose -f docker-compose.production.yml ps
```

---

## Step 7: Access Your App

Open in a browser:

```
http://YOUR_EC2_PUBLIC_IP
```

Create an account via Sign Up and start using the app.

---

## Optional: Domain + HTTPS

1. Get a domain (e.g. from Route 53 or another provider)
2. Point the domain to your EC2 public IP
3. Install Certbot for Let's Encrypt:

   ```bash
   sudo apt install certbot python3-certbot-nginx
   sudo certbot --nginx -d yourdomain.com
   ```

4. Update Nginx config to use the certbot-managed config, or keep Certbot’s auto-generated config.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| 502 Bad Gateway | `docker compose logs backend` — check Flask is up |
| Celery not processing | `docker compose logs celery` — ensure Redis and broker URL are correct |
| MongoDB connection failed | Verify Atlas IP allowlist includes EC2 IP or `0.0.0.0/0` |
| Out of memory | Use `t3.small` or larger; ensure MongoDB Atlas is used (not local Mongo) |

---

## Performance: Multi-page PDFs and evaluation time

Multi-page scripts take longer because: (1) each page is sent to OpenAI Vision for OCR, and (2) each question runs several LLM steps (rubric, scoring, consistency, feedback, explainability). The pipeline already runs **OCR pages in parallel** and **evaluation per question in parallel**; throughput is limited by Celery worker concurrency.

- **Celery concurrency** is set to `6` in `docker-compose.production.yml` so more tasks run at once. On a larger instance (e.g. 4 vCPU), you can raise it: edit the `celery` service command to `--concurrency=8` (or 10) and restart.
- **Instance size**: For many scripts or long exams, use at least `t3.small` (2 vCPU, 2 GB RAM). Prefer `t3.medium` if you run with higher concurrency.
- **Rate limits**: If you hit OpenAI rate limits, lower concurrency or add backoff; the app already uses retries.

---

## Update Deployment (deploy your latest changes)

Run this on the EC2 instance whenever you want to deploy new code:

```bash
cd ~/assessment-engine
git pull
cd frontend && npm ci && npm run build && cd ..
docker compose -f docker-compose.production.yml up -d --build
```

Or use the deploy script:

```bash
cd ~/assessment-engine
git pull
./deploy/deploy.sh
```
