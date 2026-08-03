# Staging environment matrix

All secret values are supplied through Render or Neon and never committed.

| Variable | Services | Required | Classification | Staging source | Production source | Validation |
|---|---|---:|---|---|---|---|
| `APP_ENV` | API, worker | yes | public | Blueprint: `staging` | production Blueprint | Exact supported environment |
| `APP_BASE_URL` | API, worker | yes | public | staging API HTTPS URL | production API HTTPS URL | HTTPS |
| `FRONTEND_BASE_URL` | API, worker | yes | public | staging Mini App HTTPS URL | production Mini App URL | HTTPS |
| `DATABASE_URL` | API, worker | yes | secret | isolated Neon staging project | durable production project | PostgreSQL URL, never test URL |
| `TELEGRAM_BOT_TOKEN` | API, worker | yes | secret | new staging BotFather bot | distinct production bot | Non-placeholder token |
| `TELEGRAM_WEBHOOK_SECRET` | API, worker | yes | secret | Render-generated | distinct Render-generated | At least 16 characters |
| `TELEGRAM_WEBHOOK_URL` | API, worker | yes | public | staging API `/webhook` | production API `/webhook` | HTTPS |
| `TELEGRAM_MINI_APP_URL` | API, worker | yes | public | staging static site | production site | HTTPS |
| `SESSION_SIGNING_SECRET` | API, worker | yes | secret | Render-generated | distinct Render-generated | At least 32 characters |
| `CORS_ORIGINS` | API, worker | yes | public | exact staging site origin | exact production origin | No wildcard or localhost |
| `PUBLIC_V2_ENABLED` | API, worker | yes | public | disabled before smoke migration | controlled rollout | Boolean |
| `REMINDER_WORKER_ENABLED` | API, worker | yes | public | enabled only on worker after API ready | controlled rollout | Boolean |
| `INVITE_ONLY` | API, worker | yes | public | `true` | `true` through beta | Boolean |
| `AI_AGENT_ENABLED` | API, worker | yes | public | initially `false` | controlled rollout | Requires provider and key when true |
| `AI_PROVIDER` | API, worker | yes | public | initially `disabled` | approved provider | Supported provider |
| `GROQ_API_KEY` | API, worker | conditional | secret | distinct staging key | distinct production key | Required only when AI is enabled |
| `MESSAGE_CLEANUP_ENABLED` | API, worker | yes | public | initially `false` | controlled rollout | Boolean |
| `INTERNAL_MONITORING_TOKEN` | API | recommended | secret | Render-generated | distinct Render-generated | At least 24 characters |
| `SENTRY_DSN` | API, worker | optional | secret | staging monitoring project | production monitoring project | Valid provider DSN |
| `NEXT_PUBLIC_API_URL` | static site | yes | public | staging API URL | production API URL | HTTPS; embedded at build time |
