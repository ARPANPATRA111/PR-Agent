# 🚀 Weekly Progress Agent

<div align="center">

![Version](https://img.shields.io/badge/version-1.1.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![Node](https://img.shields.io/badge/node-18+-green.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Status](https://img.shields.io/badge/status-production--ready-brightgreen.svg)

**An autonomous AI-powered agent that helps students and professionals track daily work via Telegram voice notes and automatically generates polished LinkedIn progress posts.**

[Quick Start](#-quick-start) •
[Documentation](#-documentation) •
[Demo](#-demo) •
[Contributing](#-contributing)

</div>

---

## 📋 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [What's New in v1.1](#-whats-new-in-v11)
- [Architecture](#-architecture)
- [Quick Start](#-quick-start)
- [Documentation](#-documentation)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [API Reference](#-api-reference)
- [Deployment](#-deployment)
- [Troubleshooting](#-troubleshooting)
- [Contributing](#-contributing)
- [License](#-license)

---

## 🆕 What's New in v1.1

| Feature | Description |
|---------|-------------|
| 🎨 **LinkedIn Personalization** | Posts match your exact format with historical examples |
| 📚 **56+ Week History** | Learns from your previous posts for consistent style |
| 🔒 **JWT Authentication** | Secure dashboard API with token-based auth |
| 🚦 **Rate Limiting** | Prevent API abuse with configurable limits |
| 🔄 **Error Recovery** | Automatic retries with exponential backoff |
| 🌐 **Multi-language STT** | Support for 99+ languages in voice notes |
| 💾 **Backup System** | Automated database backups with rotation |
| 📋 **Enhanced Logging** | Structured JSON logging with log rotation |
| 🐳 **Docker Optimization** | Multi-stage builds for smaller images |
| 🧪 **Unit Tests** | Comprehensive test coverage |

---

## 🎯 Overview

The Weekly Progress Agent is a production-ready autonomous system that:

| Feature | Description |
|---------|-------------|
| 🎤 **Voice Input** | Receive voice notes via Telegram bot |
| 📝 **Transcription** | Convert speech to text using OpenAI Whisper (locally) |
| 🏷️ **Classification** | Categorize content (coding, learning, debugging, etc.) |
| 💾 **Multi-tier Memory** | Store entries in Raw, Structured, Vector, and Relational formats |
| 📊 **Daily Reflections** | Generate automatic daily summaries at midnight |
| 📱 **Weekly Posts** | Create 3 LinkedIn post variants every Sunday |
| 🔔 **Smart Nudges** | Remind users to maintain consistency |
| 🎨 **Dashboard** | Beautiful Next.js UI for viewing and managing content |

---

## ✨ Key Features

### 🤖 Intelligent Processing
```
Voice Note → Whisper STT → Groq LLM Classification → Multi-tier Storage
```

### 📊 Analytics Dashboard
- Real-time statistics
- Category breakdown charts
- Streak tracking
- Entry browsing with search/filter

### 🎯 Smart Post Generation
- **Your Signature Format**: `🌟 𝐖𝐞𝐞𝐤-{N} 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 𝐑𝐞𝐩𝐨𝐫𝐭 🚀`
- **Historical Learning**: Learns from 56+ weeks of your past posts
- Based on actual week's activities
- Includes Looking Ahead, Quote of the Week sections
- Editable before posting
- One-click copy to clipboard

### ⏰ Automated Scheduling
- Daily reflections at midnight
- Weekly posts on Sunday evening
- Morning nudges at 9 AM
- Inactivity reminders after 24 hours

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACES                             │
├─────────────────────────────────┬───────────────────────────────────────┤
│         TELEGRAM BOT            │          NEXT.JS DASHBOARD            │
│    • Voice Note Input           │    • Statistics & Analytics           │
│    • Commands (/start, etc)     │    • Entry Browser                    │
│    • Notifications              │    • Post Editor                      │
└─────────────────┬───────────────┴───────────────────┬───────────────────┘
                  │                                   │
                  │ Webhook                           │ REST API
                  ▼                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI BACKEND                               │
├─────────────────────────────────────────────────────────────────────────┤
│   ┌─────────────────┐    ┌─────────────────┐    ┌───────────────────┐   │
│   │  Whisper (STT)  │    │  Groq LLM Agent │    │ APScheduler Jobs  │   │
│   │  Local model    │    │  Classification │    │ Daily/Weekly tasks│   │
│   │  base.en        │    │  Reflection     │    │ Nudges            │   │
│   └─────────────────┘    └─────────────────┘    └───────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │
┌─────────────────────────────────┴───────────────────────────────────────┐
│                           MEMORY SYSTEM                                  │
├─────────────────┬─────────────────┬─────────────────┬───────────────────┤
│   RAW MEMORY    │ STRUCTURED MEM  │  VECTOR MEMORY  │ RELATIONAL MEM    │
│   Full texts    │ JSON facts      │  ChromaDB       │ SQLite (WAL)      │
│   Audit trail   │ Categories      │  Embeddings     │ Relationships     │
└─────────────────┴─────────────────┴─────────────────┴───────────────────┘
```

---

## 📁 Project Structure

```
weekly_agent/
├── 📂 backend/                 # FastAPI Python Backend
│   ├── main.py                # Application entry point
│   ├── bot.py                 # Telegram webhook handlers
│   ├── memory.py              # Multi-tier memory system
│   ├── llm_agent.py           # LLM orchestration & prompts
│   ├── scheduler.py           # APScheduler job management
│   ├── utils.py               # Transcription & audio processing
│   ├── config.py              # Pydantic configuration
│   ├── models.py              # Pydantic data models
│   ├── requirements.txt       # Python dependencies
│   └── Dockerfile             # Container configuration
│
├── 📂 frontend/                # Next.js React Dashboard
│   ├── src/
│   │   ├── app/               # Next.js app router
│   │   │   ├── layout.tsx     # Root layout with providers
│   │   │   ├── page.tsx       # Main application page
│   │   │   └── globals.css    # Global styles
│   │   ├── components/
│   │   │   ├── ui/            # Reusable UI components
│   │   │   ├── layout/        # Header, Sidebar
│   │   │   ├── dashboard/     # Dashboard view
│   │   │   ├── entries/       # Entries view
│   │   │   ├── posts/         # Posts view
│   │   │   ├── summaries/     # Summaries view
│   │   │   └── settings/      # Settings view
│   │   └── lib/               # Utilities
│   ├── package.json
│   └── Dockerfile
│
├── 📂 prompts/                 # LLM Prompt Templates
│   ├── classification.md      # Entry categorization
│   ├── reflection.md          # Daily reflection
│   ├── weekly_report.md       # LinkedIn post generation
│   └── nudging.md             # Reminder templates
│
├── 📂 scripts/                 # Utility Scripts
│   ├── init_db.py             # Database initialization
│   └── setup_webhook.py       # Telegram webhook setup
│
├── 📂 docs/                    # Documentation
│   ├── STARTUP_GUIDE.md       # Complete setup guide
│   ├── ARCHITECTURE.md        # Technical documentation
│   ├── TEST_FLOW.md           # Testing guide
│   └── FUTURE_UPDATES.md      # Roadmap
│
├── .env.example               # Environment template
├── docker-compose.yml         # Container orchestration
└── README.md                  # This file
```

---

## 🚀 Quick Start

### Prerequisites

| Software | Version | Purpose |
|----------|---------|---------|
| Python | 3.10+ | Backend runtime |
| Node.js | 18+ | Frontend runtime |
| FFmpeg | Latest | Audio processing |

### API Keys Required

| Service | Purpose | Get Key |
|---------|---------|---------|
| Telegram | Bot interface | [@BotFather](https://t.me/BotFather) |
| Groq | LLM processing | [console.groq.com](https://console.groq.com) |

### Installation

```bash
# 1. Clone repository
git clone https://github.com/yourusername/weekly_agent.git
cd weekly_agent

# 2. Backend setup
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows
# source venv/bin/activate   # macOS/Linux
pip install -r requirements.txt

# 3. Download Whisper model
python -c "import whisper; whisper.load_model('base')"

# 4. Configure environment
cd ..
copy .env.example .env
# Edit .env with your API keys

# 5. Initialize database
python scripts/init_db.py

# 6. Start backend
cd backend
uvicorn main:app --reload --port 8000

# 7. Frontend setup (new terminal)
cd frontend
npm install
npm run dev

# 8. Set up Telegram webhook (requires ngrok for local dev)
ngrok http 8000  # In new terminal
python scripts/setup_webhook.py https://your-ngrok-url/webhook
```

### Verify Installation

| Check | URL |
|-------|-----|
| Backend Health | http://localhost:8000/api/health |
| API Docs | http://localhost:8000/docs |
| Dashboard | http://localhost:3000 |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [Startup Guide](./docs/STARTUP_GUIDE.md) | Complete setup and running instructions |
| [Architecture](./docs/ARCHITECTURE.md) | Technical diagrams and system design |
| [Test Flow](./docs/TEST_FLOW.md) | Comprehensive testing checklist |
| [Future Updates](./docs/FUTURE_UPDATES.md) | Roadmap and planned features |

---

## ⚙️ Configuration

### Environment Variables

Create a `.env` file from `.env.example`:

```env
# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_ADMIN_ID=your_user_id
WEBHOOK_URL=https://your-domain.com

# Groq LLM
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama3-70b-8192
LLM_TEMPERATURE=0.7

# Database
DATABASE_URL=sqlite:///./data/weekly_agent.db
CHROMA_PERSIST_DIR=./data/chroma

# Whisper
WHISPER_MODEL=base

# Scheduler
TIMEZONE=UTC
DAILY_REFLECTION_HOUR=23
WEEKLY_SUMMARY_DAY=6
WEEKLY_SUMMARY_HOUR=20
MORNING_NUDGE_HOUR=9
NUDGE_THRESHOLD_HOURS=24

# Frontend
NEXT_PUBLIC_API_URL=http://localhost:8000

# Security
SECRET_KEY=your_secret_key
CORS_ORIGINS=http://localhost:3000

# Logging
LOG_LEVEL=INFO
DEBUG=true
```

### Scheduler Configuration

| Job | Trigger | Description |
|-----|---------|-------------|
| Daily Reflection | 23:59 daily | Generate summary of day's entries |
| Weekly Summary | Sunday 20:00 | Generate LinkedIn post variants |
| Morning Nudge | 09:00 daily | Remind if no entry today |
| Inactivity Check | Every 6 hours | Remind if >24h since last entry |

---

## 📱 Usage

### Telegram Commands

| Command | Description |
|---------|-------------|
| `/start` | Initialize bot and create user profile |
| `/status` | Show streak and entry statistics |
| `/summary` | Get latest daily/weekly summary |
| `/generate` | Force generate LinkedIn post drafts |
| `/help` | Show all available commands |

### Voice Note Workflow

```
1. 🎤 Record voice note describing your work
   "Today I spent 3 hours fixing the authentication bug..."

2. 📤 Send to your Telegram bot

3. ✅ Receive confirmation:
   ✅ Entry logged!
   📁 Category: debugging
   🎯 Key points: Fixed auth bug, JWT tokens
   🔥 Streak: 5 days!

4. 📊 View in dashboard at http://localhost:3000
```

### Dashboard Views

| View | Features |
|------|----------|
| **Dashboard** | Stats cards, category chart, recent entries, tips |
| **Entries** | Search, filter by category, pagination, detail modal |
| **Posts** | View, edit, copy, generate new posts |
| **Summaries** | Daily reflections with productivity scores |
| **Settings** | Timezone, schedules, notification preferences |

---

## 🔌 API Reference

### Health Check
```http
GET /api/health
```
Returns system status including database and scheduler health.

### Entries
```http
GET /api/entries?page=1&limit=10&category=coding&search=python
```
Paginated list of entries with optional filters.

```http
GET /api/entries/:id
DELETE /api/entries/:id
```

### Posts
```http
GET /api/posts
GET /api/posts/:id
PUT /api/posts/:id
POST /api/generate-post
```

### Summaries
```http
GET /api/summaries
GET /api/summaries/:id
POST /api/summaries/generate
```

### Settings
```http
GET /api/settings
PUT /api/settings
```

### Webhook (Internal)
```http
POST /webhook
```
Telegram webhook receiver for bot updates.

**Full API documentation available at** http://localhost:8000/docs

---

## 🧠 Memory System

### 1. Raw Memory
- **Purpose**: Full transcripts with metadata for auditability
- **Storage**: SQLite `entries` table
- **Fields**: id, user_id, date, raw_text, audio_path, duration

### 2. Structured Memory
- **Purpose**: Extracted key facts for easy summarization
- **Storage**: SQLite JSON column `structured_data`
- **Fields**: category, topics[], key_points[], sentiment

### 3. Vector Memory
- **Purpose**: Semantic search and theme detection
- **Storage**: ChromaDB (persistent)
- **Use Cases**: Find related entries, detect recurring themes, avoid repetition

### 4. Relational Memory
- **Purpose**: Structured queries for summaries and reports
- **Storage**: SQLite tables (users, entries, summaries, posts)
- **Use Cases**: Daily/weekly aggregations, user tracking

---

## 🚢 Deployment

### Docker (Recommended)

```bash
# Build and run all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

### Manual Deployment

#### Backend (Railway/Fly.io)
1. Connect GitHub repository
2. Set environment variables
3. Deploy
4. Update Telegram webhook URL

#### Frontend (Vercel)
1. Import from GitHub
2. Set `NEXT_PUBLIC_API_URL`
3. Deploy

### Production Checklist

- [ ] SSL certificate configured
- [ ] Environment variables set
- [ ] Database backed up
- [ ] Webhook URL updated
- [ ] Monitoring enabled
- [ ] Rate limiting configured

---

## 🔧 Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| FFmpeg not found | Install FFmpeg and add to PATH |
| Whisper model fails | Run `pip install --upgrade openai-whisper` |
| Database locked | Stop all Python processes, delete `.db-wal` and `.db-shm` files |
| Webhook not receiving | Check ngrok URL, re-run `setup_webhook.py` |
| Groq API error | Verify API key, check rate limits |
| Frontend CORS error | Check `CORS_ORIGINS` in `.env` |

### Debug Mode

Set `DEBUG=true` in `.env` for verbose logging.

### Getting Help

1. Check [Startup Guide](./docs/STARTUP_GUIDE.md)
2. Review [Test Flow](./docs/TEST_FLOW.md)
3. Check backend logs: `docker-compose logs backend`
4. Open GitHub Issue with logs and steps

---

## 🎬 Demo

### Voice Processing
```
User: [Voice note] "Today I worked on implementing OAuth2 
       authentication. Took about 4 hours but finally got 
       it working with Google and GitHub providers."

Bot:  ✅ Entry logged!
      📁 Category: coding
      🎯 Key points:
      • Implemented OAuth2 authentication
      • Integrated Google provider
      • Integrated GitHub provider
      🔥 Streak: 7 days!
```

### LinkedIn Post Generation
```
📝 Professional:
"This week's engineering focus: authentication infrastructure. 
Successfully implemented OAuth2 with multiple providers, 
improving user onboarding efficiency by an estimated 40%. 
Key technical challenges included state management and 
secure token storage. #SoftwareEngineering #OAuth2"

🎉 Casual:
"Week 12 in the books! Finally cracked OAuth2 authentication 
this week 🔐 Google and GitHub logins are now live! The journey 
from confused to confident was real. What auth challenges 
have you tackled lately? #BuildInPublic #DevLife"

✨ Inspirational:
"Every complex system starts with a single commit. This week, 
I transformed authentication from a blocker into a feature. 
Lesson learned: patience + persistence = progress. What's 
your breakthrough moment? #GrowthMindset #TechJourney"
```

---

## 🤝 Contributing

We welcome contributions! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing`)
5. Open a Pull Request

### Development Setup

```bash
# Install dev dependencies
pip install -r requirements-dev.txt  # Backend
npm install                          # Frontend

# Run tests
pytest                               # Backend
npm test                             # Frontend

# Format code
black .                              # Python
npm run lint                         # TypeScript
```

---

## 📄 License

MIT License - feel free to use for personal or commercial projects.

---

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [OpenAI Whisper](https://github.com/openai/whisper) - Speech recognition
- [Groq](https://groq.com/) - Fast LLM inference
- [Next.js](https://nextjs.org/) - React framework
- [Radix UI](https://radix-ui.com/) - UI primitives
- [ChromaDB](https://www.trychroma.com/) - Vector database
- [APScheduler](https://apscheduler.readthedocs.io/) - Task scheduling

---

<div align="center">

**Built with ❤️ for productivity enthusiasts**

[⬆ Back to Top](#-weekly-progress-agent)

</div>
