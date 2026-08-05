# Keeping the free API awake

Render suspends a free web service after roughly 15 minutes without inbound
HTTP traffic. A suspended service still receives Telegram webhooks, but the
cold start adds close to a minute before the first reply, and nothing runs in
the meantime — so reminders, the Telegram message cleanup sweep, and the Sunday
digest are all delayed until something wakes the service.

This deployment uses two independent layers.

## Why a database cron cannot do this

A scheduled job inside PostgreSQL (Neon `pg_cron`, or any write/delete loop)
does not help. Render's idle timer is driven by **inbound HTTP requests to the
Render service**. A query running inside Neon never reaches Render — while the
API is suspended there is no process holding a database connection at all, so
the writes happen entirely inside Neon and Render's timer keeps running.

Neon also cannot call out over HTTP: `pg_cron` executes SQL only, and Neon does
not expose the `pg_net` or `http` extensions that would be needed to reach the
API. `pg_cron` additionally requires a compute that never autosuspends.

The ping has to originate from outside Render and arrive as real HTTP traffic.

## Layer 1: in-process self-ping

`backend/keep_alive.py` runs inside the API. Every
`KEEP_ALIVE_INTERVAL_SECONDS` (default 600) it sends a `HEAD` request to its
own public `APP_BASE_URL` + `/health`. Because the request travels out to the
platform edge and back in, it resets the idle timer exactly like user traffic.

Enable it with:

```
KEEP_ALIVE_ENABLED=true
KEEP_ALIVE_INTERVAL_SECONDS=600
```

`APP_BASE_URL` must be the absolute public URL. A loopback address is rejected
at startup, because a request to `localhost` never traverses the edge and would
not reset anything.

Verify from `GET /ready`: `components.keep_alive` reports `running`,
`misconfigured`, or `disabled`. The `/internal/metrics` endpoint exposes the
`keep_alive_pings` and `keep_alive_failures` counters.

**This layer cannot wake a service that has already slept.** Once the process
is suspended there is nothing running to send the request.

## Layer 2: external scheduled ping

`.github/workflows/keepalive.yml` covers the gap after a redeploy, a crash, or
any window where the process was not alive to ping itself. It runs every 10
minutes and pings five times across its own window, because GitHub's scheduled
runs are best-effort and are frequently delayed during peak load. Actions
minutes are free for public repositories.

Point it at a different host by setting the `KEEP_ALIVE_URL` repository
variable (Settings → Secrets and variables → Actions → Variables).

**Known limitation:** GitHub disables scheduled workflows in a repository with
60 days of no activity. If development pauses for that long, the schedule stops
silently. For a bot people depend on daily, add a second external pinger that
does not share this failure mode — [cron-job.org](https://cron-job.org) is free,
has one-minute resolution, and emails on failure. Point it at
`https://<api-host>/health` every 10 minutes.

## Budget

Staying awake continuously consumes free-tier allowances that idling does not.
Check both after the first week:

- **Render** includes roughly 750 free instance-hours per month per workspace.
  A month of continuous uptime is about 730 hours. It fits, but leaves almost
  no headroom, and a second free web service in the same workspace would not.
  The static site does not consume instance hours.
- **Neon** suspends its compute after about 5 minutes of inactivity. Keeping
  the API awake means the inline worker polls continuously, so the Neon compute
  also stops suspending and starts billing compute hours around the clock.
  `INLINE_STAGING_POLL_INTERVAL_SECONDS` was raised from 15 to 30 to halve that
  load. Confirm actual consumption against the Neon usage dashboard before
  assuming it fits the free allowance.

If either allowance is exceeded, the honest fix is an always-on paid instance
rather than a tighter ping schedule.
