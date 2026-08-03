# Availability and scale-to-zero

The staging and production topology does not use synthetic database writes or
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
