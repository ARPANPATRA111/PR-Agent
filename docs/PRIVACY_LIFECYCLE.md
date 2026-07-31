# Privacy, export, deletion, and Telegram cleanup

## Data export

An authenticated user can download an immediate private export from the Mini
App in either:

- JSON
- a ZIP containing one UTF-8 CSV per record type

Exports include profile and preferences, work logs, notes, reminders, ledger
entries, nutrition logs/items, goals, and Sunday-summary delivery metadata.
They exclude session tokens, signing data, idempotency keys, internal provider
metadata, message-cleanup metadata, hidden reasoning, and every other tenant's
rows.

Exports are assembled in memory and returned with `Cache-Control: no-store`,
`X-Content-Type-Options: nosniff`, and an attachment filename. No public object
URL is created.

## Account deletion

`DELETE /api/v2/account` requires:

1. a valid persisted Telegram Mini App session;
2. authentication issued within the configured recent-auth window;
3. the exact phrase `DELETE MY ACCOUNT`;
4. an explicit acknowledgement boolean; and
5. the Mini App's final browser confirmation.

The deletion transaction first disables reminders and Sunday schedules, then
removes the owner row. Database cascades remove all public-v2 records and
sessions. The service also removes matching legacy raw/structured data,
summaries, generated posts, goals, relational search copies, and the legacy
user profile when those legacy tables exist.

The only retained deletion receipt is a keyed, pseudonymous identity hash,
random deletion ID, timestamp, and legacy-row count. It contains no Telegram ID
or record content. Calling the deletion service again after the account is gone
is idempotent. A user who later registers again can delete the new account.

## Persisted sessions

New Mini App logins store only a SHA-256 token fingerprint, token ID, owner ID,
expiry, and optional revocation time. With public-v2 enabled, every authenticated
request must match an active persisted session. Logout revokes the current
session, and account deletion removes all sessions by foreign-key cascade.

## Telegram message cleanup

Cleanup is disabled by default and must be explicitly enabled:

```text
MESSAGE_CLEANUP_ENABLED=true
MESSAGE_CLEANUP_DELAY_SECONDS=3600
```

After the handler has committed structured data and sent its response, the
system queues the inbound message identifier. Successful outbound bot messages
are also queued. The database stores only owner ID, chat ID, message ID,
direction, purpose, timestamps, and cleanup state—never message text.

The durable worker claims due cleanup rows with the same lease/backoff pattern
used for reminders. Telegram deletion is best effort:

- deletion success (and "already gone") marks the row deleted;
- transient network failures retry with bounded backoff;
- permanent errors and exhausted retries are dead-lettered;
- cleanup failure never rolls back or deletes the saved application record.

Telegram limits whether and when a bot can delete messages, so permanent
failure is observable but does not affect the user's stored record.

## Retention

The worker runs an idempotent retention sweep. It removes expired export
request metadata, expired or old revoked sessions, old completed cleanup rows,
old processed-update receipts, and stale rate-limit buckets. It does not delete
user records.

```text
OPERATIONAL_METADATA_RETENTION_DAYS=30
OPERATIONAL_PRUNE_INTERVAL_SECONDS=3600
```

Sunday-summary message text and aggregate snapshots are cleared immediately
after successful delivery or terminal failure. Only delivery metadata remains.
