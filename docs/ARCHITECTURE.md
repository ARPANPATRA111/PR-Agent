# Architecture

```text
Telegram ── signed Mini App data ──> FastAPI API ──> PostgreSQL
    │                                  │                 ▲
    └── secret webhook ────────────────┤                 │
                                       ├── bounded AI ───┤
                                       │   proposals      │
                                       └── durable worker ┘
                                                │
                                                └── Telegram delivery
```

The API authenticates Telegram users, enforces invite access, owns CRUD, and
accepts deduplicated webhook updates. Domain services derive `owner_id` from
server-side identity and are the only supported write boundary. PostgreSQL
stores tenant records, idempotency keys, quotas, sessions, delivery leases,
agent audit envelopes, cleanup state, and worker heartbeats.

The worker is a separate process and image command. It atomically claims due
reminders and opt-in Sunday digests, sends through Telegram, retries bounded
transient failures, and dead-letters terminal work. More than one worker may
run because claim leases and unique delivery keys prevent duplicate sends.

AI never receives database or identity tools. It may only propose a strict
typed action; deterministic validation, authorization, confidence policy,
confirmation, quotas, and domain services decide whether a write occurs.
Slash commands and the Mini App work when AI is disabled or unavailable.

Public-v2 stores timestamps in UTC with an explicit user timezone, money in
integer minor units separated by currency, and nutrition estimates as editable
drafts. The legacy report API and unbounded legacy agent are returned as 404
whenever `PUBLIC_V2_ENABLED=true`.
