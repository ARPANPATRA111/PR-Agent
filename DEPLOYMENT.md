# Weekly Progress Agent - Free Deployment Guide

This guide covers deploying the Weekly Progress Agent for FREE while maintaining security for personal use.

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Security Setup](#security-setup)
4. [Backend Deployment Options](#backend-deployment-options)
   - [Option A: Render.com (Easiest)](#option-a-rendercom-easiest)
   - [Option B: Fly.io (Free Persistent Storage)](#option-b-flyio-free-persistent-storage)
   - [Option C: Railway.app (Alternative)](#option-c-railwayapp-alternative)
5. [Frontend Deployment (Vercel)](#frontend-deployment-vercel)
6. [Database Persistence](#database-persistence)
7. [Telegram Bot Security](#telegram-bot-security)
8. [Environment Variables](#environment-variables)
9. [Post-Deployment Steps](#post-deployment-steps)
10. [Maintenance & Monitoring](#maintenance--monitoring)

---

## Important: Python Version

**This project requires Python 3.12.x**. ChromaDB (vector database) is incompatible with Python 3.14+.
The `.python-version` and `runtime.txt` files ensure the correct version is used during deployment.

---

## Architecture Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Telegram API  │────▶│  Backend (Render)│────▶│  PostgreSQL     │
│    (Webhooks)   │     │   FastAPI/Python │     │  (Neon - Cloud) │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                               │                        │
                               ▼                        │
                        ┌──────────────────┐     ┌──────┴───────────┐
                        │ Frontend (Vercel)│     │ ChromaDB (Local) │
                        │   Next.js/React  │     │ Vector Storage   │
                        └──────────────────┘     └──────────────────┘
```

**Free Tier Limits:**
- **Render.com**: 750 hours/month free (but disk storage is premium - $7/month)
- **Fly.io**: 3 shared VMs free, 3GB persistent volume free
- **Railway.app**: $5 free credits/month
- **Neon PostgreSQL**: 3GB free storage
- **Vercel**: Unlimited for hobby projects
- **Groq API**: Free tier with rate limits (sufficient for personal use)

---

## Prerequisites

1. **GitHub Account** - For repository hosting
2. **Telegram Account** - To create and manage the bot
3. **Groq Account** - For LLM API access (free)
4. **Render Account** - For backend hosting (free)
5. **Vercel Account** - For frontend hosting (free)

---

## Security Setup

### 1. Telegram Bot Security (CRITICAL)

Your bot should ONLY respond to YOUR Telegram ID. This is handled via `TELEGRAM_ADMIN_ID`.

```python
# In bot.py - Already implemented
async def handle_update(self, update: TelegramUpdate) -> None:
    # Verify user is authorized
    user_id = message.from_user.id if message.from_user else None

    # Only allow your Telegram ID
    if user_id != settings.telegram_admin_id:
        await self.telegram.send_message(
            chat_id,
            "⛔ Unauthorized. This bot is private."
        )
        return
```

**To get your Telegram ID:**
1. Message [@userinfobot](https://t.me/userinfobot) on Telegram
2. It will reply with your ID (e.g., `1506240135`)

### 2. API Security

The backend uses several security measures:

- **Rate Limiting**: Prevents abuse (already configured)
- **CORS**: Only allows your frontend domain
- **Webhook Verification**: Telegram webhook URL includes a secret path

### 3. Environment Variables Security

NEVER commit `.env` files. Use platform-specific secret management:
- Render: Environment Variables in Dashboard
- Vercel: Environment Variables in Project Settings

---

## Backend Deployment Options

Choose one of the following options based on your needs:

| Platform | Free Persistent Storage | Ease of Setup | Best For |
|----------|------------------------|---------------|----------|
| Render.com | No ($7/month for disk) | Easiest | Quick testing, or if you can pay $7/month |
| Fly.io | Yes (3GB free) | Moderate | **Recommended for free deployment** |
| Railway.app | Yes ($5 credits/month) | Easy | Alternative with good UX |

---

### Option A: Render.com (Easiest)

> **Note**: Render's persistent disk is a premium feature ($7/month). Without disk, ChromaDB data will be lost on restart. Use Fly.io for truly free deployment with persistence.

#### Step 1: Deploy on Render

1. Go to [render.com](https://render.com) and sign in with GitHub

2. Click **"New +"** → **"Blueprint"** and select your repository
   - The `render.yaml` in the repo will auto-configure the service

3. Or manually create a **Web Service**:
   - **Name**: `weekly-progress-agent`
   - **Root Directory**: `backend`
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. Add environment variables (Settings → Environment):
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token
   TELEGRAM_ADMIN_ID=your_telegram_id
   GROQ_API_KEY=your_groq_key
   DATABASE_URL=your_neon_postgres_url
   SECRET_KEY=generate_random_32_char_string
   CHROMA_PERSIST_DIR=./data/chroma
   DEBUG=false
   ```

5. Deploy!

#### Step 2: Get Your Backend URL

After deployment, note your URL (e.g., `https://weekly-progress-agent.onrender.com`)

---

### Option B: Fly.io (Free Persistent Storage) - RECOMMENDED

Fly.io offers free persistent volumes, making it ideal for ChromaDB storage.

#### Step 1: Install Fly CLI

```bash
# Windows (PowerShell)
powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"

# Or download from https://fly.io/docs/hands-on/install-flyctl/
```

#### Step 2: Create fly.toml

Create `fly.toml` in the project root:

```toml
app = "weekly-progress-agent"
primary_region = "sin"  # Singapore, change to your nearest region

[build]
  dockerfile = "Dockerfile"

[env]
  CHROMA_PERSIST_DIR = "/data/chroma"
  DEBUG = "false"
  LOG_LEVEL = "INFO"

[mounts]
  source = "weekly_agent_data"
  destination = "/data"

[[services]]
  internal_port = 8000
  protocol = "tcp"

  [[services.ports]]
    handlers = ["http"]
    port = 80

  [[services.ports]]
    handlers = ["tls", "http"]
    port = 443

  [[services.http_checks]]
    path = "/health"
    interval = 10000
    timeout = 2000
```

#### Step 3: Create Dockerfile

Create `Dockerfile` in the project root:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .

RUN mkdir -p /data/chroma

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### Step 4: Deploy to Fly.io

```bash
# Login to Fly
fly auth login

# Launch app (first time)
fly launch --no-deploy

# Create persistent volume (1GB free)
fly volumes create weekly_agent_data --size 1 --region sin

# Set secrets
fly secrets set TELEGRAM_BOT_TOKEN=your_token
fly secrets set TELEGRAM_ADMIN_ID=your_id
fly secrets set GROQ_API_KEY=your_key
fly secrets set DATABASE_URL=your_neon_postgres_url
fly secrets set SECRET_KEY=your_random_secret

# Deploy
fly deploy
```

#### Step 5: Get Your Backend URL

Your app will be at `https://weekly-progress-agent.fly.dev`

---

### Option C: Railway.app (Alternative)

Railway provides $5 free credits per month with persistent storage.

1. Go to [railway.app](https://railway.app) and sign in with GitHub

2. Click **"New Project"** → **"Deploy from GitHub repo"**

3. Select your repository and configure:
   - **Root Directory**: `backend`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

4. Add environment variables in **Variables** tab

5. Deploy!

---

## Frontend Deployment (Vercel)

### Step 1: Deploy on Vercel

1. Go to [vercel.com](https://vercel.com) and sign in with GitHub

2. Click **"Add New..."** → **"Project"**

3. Import your GitHub repository

4. Configure:
   - **Framework Preset**: Next.js
   - **Root Directory**: `frontend`

5. Add environment variables:
   ```
   NEXT_PUBLIC_API_URL=https://your-backend-url.onrender.com
   ```

6. Deploy!

### Step 2: Update CORS

After deployment, update your backend's CORS settings:

1. Go to Render dashboard
2. Add/update environment variable:
   ```
   CORS_ORIGINS=https://your-frontend.vercel.app,http://localhost:3000
   ```

---

## Database Persistence

### Option A: Render Disk (Recommended for Free)

Already configured above. SQLite + ChromaDB will persist on a 1GB disk.

### Option B: External Database (More Reliable)

For production use, consider:

1. **Supabase** (Free PostgreSQL):
   - 500MB database free
   - Replace SQLite with PostgreSQL
   - Update `DATABASE_URL=postgresql://...`

2. **PlanetScale** (Free MySQL):
   - 5GB storage free
   - Requires SQLAlchemy MySQL driver

---

## Telegram Bot Security

### Only Allow Your User ID

Ensure `_is_authorized()` check in bot.py:

```python
async def handle_update(self, update: TelegramUpdate) -> None:
    message = update.message
    if not message:
        return

    user_id = message.from_user.id if message.from_user else None

    # CRITICAL: Only allow your Telegram ID
    if user_id != settings.telegram_admin_id:
        logger.warning(f"Unauthorized access attempt from user {user_id}")
        return  # Silently ignore unauthorized users
```

### Set Webhook with Secret Path

When setting webhook, use a secret path:

```python
# In setup_webhook.py
webhook_url = f"{base_url}/webhook/{SECRET_TOKEN}"
```

### Disable Bot Visibility

1. Message [@BotFather](https://t.me/botfather)
2. Select your bot
3. Go to **Bot Settings** → **Allow Groups?** → **Turn off**
4. This prevents others from adding your bot to groups

---

## Environment Variables

### Backend (.env)

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_ADMIN_ID=your_telegram_id

# Groq LLM
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile

# Database
DATABASE_URL=sqlite:///./data/weekly_agent.db
CHROMA_PERSIST_DIR=./data/chroma

# Security
SECRET_KEY=generate_with_openssl_rand_hex_32
CORS_ORIGINS=https://your-frontend.vercel.app

# Whisper
WHISPER_MODEL=base
WHISPER_LANGUAGE=auto

# Production
DEBUG=false
LOG_LEVEL=INFO
```

### Frontend (.env.local)

```env
NEXT_PUBLIC_API_URL=https://your-backend.onrender.com
```

---

## Post-Deployment Steps

### 1. Set Telegram Webhook

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -d "url=https://your-backend.onrender.com/webhook"
```

Or use the setup script:

```bash
python scripts/setup_webhook.py https://your-backend.onrender.com
```

### 2. Verify Webhook

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

### 3. Test the Bot

1. Open Telegram
2. Message your bot with `/start`
3. Send a voice note
4. Check the frontend dashboard

### 4. Flush Development Data

Before going live, clear test data:

```powershell
.\scripts\flush.ps1 -Force
```

---

## Maintenance & Monitoring

### Render Free Tier Limitations

- Service spins down after 15 minutes of inactivity
- First request after spin-down takes ~30 seconds
- **Solution**: Use a health check to keep it awake

### Keep-Alive Script (Optional)

Create a cron job to ping your backend every 10 minutes:

```python
# keep_alive.py
import requests
import time

BACKEND_URL = "https://your-backend.onrender.com/health"

while True:
    try:
        response = requests.get(BACKEND_URL, timeout=30)
        print(f"[{time.strftime('%H:%M:%S')}] Health check: {response.status_code}")
    except Exception as e:
        print(f"[{time.strftime('%H:%M:%S')}] Health check failed: {e}")

    time.sleep(600)  # 10 minutes
```

Or use [UptimeRobot](https://uptimerobot.com) (Free, 50 monitors):
1. Create account
2. Add HTTP monitor for `https://your-backend.onrender.com/health`
3. Set interval to 5 minutes

### Log Monitoring

1. Render provides logs in the dashboard
2. Check for errors in **Logs** tab
3. Set up alerts for deployment failures

---

## Troubleshooting

### Bot Not Responding

1. Check webhook is set correctly:
   ```bash
   curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
   ```

2. Check Render logs for errors

3. Verify `TELEGRAM_ADMIN_ID` matches your ID

### Frontend Can't Connect to Backend

1. Check CORS settings include your Vercel domain
2. Verify `NEXT_PUBLIC_API_URL` is correct
3. Check browser console for errors

### Database Errors

1. Ensure Render disk is attached
2. Check disk isn't full (1GB limit)
3. Verify mount path is correct

### Voice Notes Not Working

1. Whisper requires sufficient memory
2. Consider using `WHISPER_MODEL=tiny` for free tier
3. Check audio temp directory permissions

---

## Cost Summary

| Service | Monthly Cost | Notes |
|---------|--------------|-------|
| Render | $0 | 750 free hours/month |
| Vercel | $0 | Unlimited for hobby |
| Groq | $0 | Free tier with limits |
| Telegram | $0 | Always free |
| **Total** | **$0** | Perfect for personal use |

---

## Security Checklist

- [ ] `TELEGRAM_ADMIN_ID` set to YOUR ID only
- [ ] `.env` file in `.gitignore`
- [ ] `DEBUG=false` in production
- [ ] Strong `SECRET_KEY` generated
- [ ] CORS restricted to your frontend domain
- [ ] Webhook URL not publicly shared
- [ ] Bot groups disabled in BotFather
- [ ] Rate limiting enabled

---

## Quick Commands Reference

```bash
# Deploy to Render (after git push)
git push origin main

# Set webhook
python scripts/setup_webhook.py https://your-backend.onrender.com

# Check webhook
curl "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"

# Flush data before production
.\scripts\flush.ps1 -Force

# Health check
curl https://your-backend.onrender.com/health
```

---

Happy deploying! 🚀
