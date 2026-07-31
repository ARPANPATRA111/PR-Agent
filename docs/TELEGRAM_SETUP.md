# Telegram setup and rollback

Use a distinct Telegram bot for each environment. Store the token and webhook
secret in the environment, never in shell history or tracked files.

```powershell
$env:TELEGRAM_BOT_TOKEN = "<secret from the platform vault>"
$env:TELEGRAM_WEBHOOK_SECRET = "<random secret>"
python scripts/setup_webhook.py https://staging-api.example.invalid
python scripts/setup_webhook.py --info
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
