# Secret Rotation Checklist

No secret values belong in this document, source control, issue text, build
logs, or commit messages.

## Immediate owner actions

- [ ] Revoke and replace the current Telegram bot token through BotFather.
- [ ] Revoke and replace the current Groq API key.
- [ ] Replace the legacy application/JWT signing secret.
- [ ] Review Render and any other hosting environment for copied legacy values.
- [ ] Confirm that staging and production use different credentials.
- [ ] Remove stale webhook registrations only through an authenticated CLI
      using the intended bot and environment.

The local `.env` contains live-looking Telegram and Groq credentials. Phase 0
does not edit or delete that owner file. Do not deploy from it.

## Public-v2 credentials

Create separate development, test, staging, and production values for:

- `DATABASE_URL`
- `TEST_DATABASE_URL`
- `SESSION_SIGNING_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`
- `TELEGRAM_WEBHOOK_URL`
- `TELEGRAM_MINI_APP_URL`
- `GROQ_API_KEY`
- `OPENAI_API_KEY`, only if that provider is enabled
- `REDIS_URL`, when Redis-backed controls are enabled
- `SENTRY_DSN`, when monitoring is configured

## Rotation procedure

For each environment:

1. Create the replacement in the provider console or secret manager.
2. Store it only in the target environment's protected secret storage.
3. Deploy the consumer configured for the replacement.
4. Validate health without printing the value.
5. Revoke the old credential.
6. Confirm the old credential no longer works.
7. Record the rotation date and owner outside the repository.

## Verification

- [ ] `.env.example` contains placeholders only.
- [ ] `gitleaks` passes against the tracked branch and Git history.
- [ ] Frontend bundles contain no dashboard password, signing secret, bot
      token, webhook secret, provider key, or database URL.
- [ ] Application logs redact authentication headers, cookies, Telegram
      `initData`, message content, and provider payloads.
- [ ] No credentials appear in Docker image layers or deployment manifests.
- [ ] Backup access credentials are separate from application credentials.

If a live credential is ever committed, rotate it immediately. Removing it from
the latest commit does not make the credential safe.
