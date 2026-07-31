# Reminder worker

The standalone `python worker.py` process handles reminder occurrences,
opt-in Sunday digests, Telegram cleanup, retention pruning, and a content-free
heartbeat. It requires `PUBLIC_V2_ENABLED=true`,
`REMINDER_WORKER_ENABLED=true`, PostgreSQL, and a Telegram bot token.

Due work is claimed in a transaction with a lease. Unique occurrence keys make
delivery idempotent; another worker cannot claim the same live lease and may
recover it after expiry. Transient failures use bounded exponential backoff.
Permanent errors and exhausted attempts become dead letters visible through
protected operational metrics. Paused, edited, deleted, or account-deleted
reminders are checked again before network delivery.

Deploy the worker independently from the API and only after migrations finish.
Disable `REMINDER_WORKER_ENABLED` before incident work that must stop outbound
messages.
