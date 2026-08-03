# Telegram setup and rollback

Use a distinct Telegram bot for each environment. Store the token and webhook
secret in the environment, never in shell history or tracked files.

For the correct-account free staging deployment, create a new bot through the
verified `@BotFather` account. Mark its name and description as staging. Keep
the returned token in a password manager, then paste it directly into the new
API service's masked `TELEGRAM_BOT_TOKEN` field. Never send it through chat.

The proposed new Mini App is
`https://pr-agent-r24-staging-web.onrender.com`, but configure BotFather only
after that exact URL is live in the verified correct Render account. Do not use
`https://pr-agent-staging-web.onrender.com`; it belongs to the earlier mistaken
deployment.

BotFather navigation:

1. `/newbot` and create a clearly labelled staging bot.
2. `/mybots` -> staging bot -> **Edit Bot** to set its staging name, about text,
   and description.
3. `/mybots` -> staging bot -> **Bot Settings** -> **Configure Mini App**.
4. Set the menu label to `Open PR Agent` and the live new static-site HTTPS URL.

```powershell
$env:TELEGRAM_BOT_TOKEN = "<secret from the platform vault>"
$env:TELEGRAM_WEBHOOK_SECRET = "<random secret>"
python scripts/setup_webhook.py https://staging-api.example.invalid
python scripts/setup_webhook.py --info
python scripts/register_bot_commands.py
python scripts/register_bot_commands.py --verify-only
```

Replace the placeholder URL only at execution time. The script registers
`/webhook`, restricts updates to messages, and sends Telegram's secret-token
header configuration.

Rollback to a previous healthy API by running the setup command with that
API's HTTPS base URL. To stop delivery without discarding pending Telegram
updates:

```powershell
python scripts/setup_webhook.py --delete
```

Deleting a webhook does not disable the worker. Disable
`REMINDER_WORKER_ENABLED` separately when pausing all outbound processing.

For free staging, keep `REMINDER_WORKER_ENABLED=false` and
`INLINE_STAGING_WORKER_ENABLED=true`. Because Render Free does not provide a
service shell, create an invite from a trusted workstation with staging-only
`DATABASE_URL` configured by running
`python backend/admin_cli.py create-invite --expires-days 14`. Deliver the
one-time code through a private channel and do not retain it in deployment
notes.

The free deployment disclosure appears in `/help`. AI intent extraction and
voice transcription are disabled; deterministic CRUD commands remain usable.
