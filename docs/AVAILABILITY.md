# Availability and scale-to-zero

No topology uses synthetic database writes, external keep-alive monitors, or
self-pings to imitate user traffic.

Render Free web services suspend after an idle interval based on inbound HTTP
or WebSocket traffic. Database activity does not keep a Render web service
running. The API and durable delivery worker therefore require paid,
always-running instances before reminder delivery can be called reliable. The
Mini App is a static site and does not need an always-running process.

Neon scale-to-zero is expected behavior. A suspended compute resumes on the
next connection without losing stored data. Staging should retain the default
scale-to-zero setting. Production may disable it on a paid Neon plan only when
measured wake latency justifies the extra compute cost.

## Free staging mode

`render.free.yaml` enables `INLINE_STAGING_WORKER_ENABLED` only on its single
staging API instance. The FastAPI lifespan starts one bounded polling loop. It
reuses the production `DurableDeliveryStore`, including PostgreSQL row locks,
unique occurrence keys, retry leases, and recorded scheduled/delivery times.
The loop runs once on startup, can be nudged by a valid Telegram update or
authenticated API activity, polls only while the process is awake, and shuts
down with the API.

Recurring schedules create at most one catch-up delivery per due schedule in a
sweep and advance from the current time, so missed recurring intervals are not
replayed as a flood. `WORKER_BATCH_SIZE` bounds each sweep. One-time reminders
remain deliverable after wake-up rather than being silently discarded. Sunday
summaries use the same once-per-user/week constraint.

The public disclosure is:

> This free staging deployment can sleep when inactive. Telegram commands wake
> it automatically, but the first response may be delayed. Scheduled reminders
> and Sunday summaries are best-effort and may arrive late while the service is
> sleeping.

There is no exact-time guarantee on free staging. Production continues to use
the separate durable worker from `render.yaml`.

The durable worker already writes a content-free heartbeat while it is active.
Adding one cron job to insert a row and another to delete it would create WAL,
backup, and billing churn while failing to keep the Render API awake. Such jobs
must not be added as availability controls.

Use these operational signals instead:

- Render service state and restart history
- `GET /health` for liveness
- `GET /ready` for API and database readiness
- authenticated `GET /internal/metrics` for worker heartbeat and delivery lag
- provider-native Neon compute and connection metrics

An operator can request one protected sweep from a trusted workstation or CI
runner that has the staging secrets with `python admin_cli.py run-jobs-once`.
Render Free web services do not provide shell or one-off-job access. No public
sweep endpoint exists.
