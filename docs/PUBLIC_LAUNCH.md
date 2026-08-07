# Public launch: readiness assessment and checklist

## Verdict

**Not ready to ship publicly yet. Not far off, but not yet.**

Nothing here is a design flaw. The blockers are all of one kind: the code has
never been exercised against reality. Every capability below is covered by
unit tests and none of it has served a real user, because the branch has not
been deployed. Shipping to strangers straight from a green test suite would be
guessing.

The honest summary: the bot can now *do* what it is supposed to do, and the
security model is sound. What is missing is evidence that it does so live,
plus three things a public service needs that a private one does not —
observability, a privacy policy, and a plan for when the provider says no.

## Can it do what the project set out to do?

The goal was a voice-first personal tracker. Measured against that:

| Capability | State |
|---|---|
| Create work, notes, money, reminders, goals, meals by voice | Implemented, unit-tested |
| Ask what you recorded, search it, filter by date/status | Implemented, unit-tested |
| Edit an existing record by voice | Implemented, unit-tested |
| Pause/resume, complete, pin, confirm a food draft | Implemented, unit-tested |
| Record goal progress | Implemented, unit-tested |
| Change settings/timezone by voice | Implemented, unit-tested |
| Delete by description, never by ID | Implemented, unit-tested |
| Answer a follow-up question conversationally | Implemented, unit-tested |
| Ordinary conversation and general knowledge | Implemented, unit-tested |
| Works without ever typing a command | Implemented, **unproven live** |
| Reminders arrive on time | **Best-effort only** — see below |
| Nutrition numbers are accurate | **Estimates, not measurements** |

So the answer to "is it able to do what it is supposed to do" is: on paper and
in tests, yes, and considerably more than a month ago. Live, unknown.

## Blockers — do not launch publicly until each is cleared

### B1. Nothing is deployed

`origin/public-v2` is still at `66d8e84`. Every capability in the table above
exists only locally. This is also why recent manual testing looked broken: the
bot answering on Telegram is the old build, which had no listing action, no
reference resolution, and printed `/answeragent <id>` at the user.

*Clear it by:* pushing the branch, confirming Render deploys the new commit,
and confirming `/ready` reports `migration_revision: j5f7b9c1e3a4`.

### B2. The intent schema has never met the real model

The strict JSON schema sent to Groq now has 16 action variants and is about
15 KB. That is a large structured-output request. It is well formed and
self-contained, but whether the live model reliably produces valid output
across all 16 kinds — especially the nested `selector` object — is untested.

This is the single highest risk in the release. If it degrades, every request
falls back to the non-strict model and quality drops silently.

*Clear it by:* running the live voice test plan end to end and confirming the
new action kinds actually fire. Watch for `Intent provider attempt failed` and
`Intent provider recovery succeeded` in the logs; frequent recovery means the
strict path is failing and the schema needs splitting.

### B3. No observability

There is a `/internal/metrics` endpoint and JSON logs. There is no alerting.
With invited testers this is fine, because they tell you. Public users do not
report bugs — they leave. A silent failure could run for days.

*Clear it by:* setting `SENTRY_DSN`, and putting an uptime monitor on `/ready`
that alerts you rather than just recording. At minimum you must be paged when
`/ready` fails or the assistant error rate spikes.

### B4. Provider capacity is unbounded and unmonitored

Quotas are now off by design (`QUOTAS_ENABLED=false`) — a deliberate
early-stage choice, and reasonable while the user base is small. But one Groq
key serves everyone, and Groq's own organisation rate limits are shared. Under
even modest concurrency, requests will start failing with 429 and every user
sees "temporarily unavailable" at once.

The per-minute HTTP rate limit still applies, so a runaway loop is contained.
The clarification loop that could previously burn calls indefinitely is fixed
and capped at two rounds.

*Clear it by:* deciding what happens at the limit before it happens. Either
accept degradation and make the message honest, or re-enable `QUOTAS_ENABLED`
with generous values. Watch Groq's dashboard during the first week.

### B5. No privacy policy

The bot stores personal financial and health-adjacent data and sends voice to
a third-party provider for transcription. For users in India the DPDP Act
consent requirements apply. This is a legal blocker, not a nice-to-have.

*Clear it by:* publishing a policy covering what is stored, where it goes,
retention, and the export/delete path; linking it from `/start` and the Mini
App.

### B6. Secrets have been used in a pre-public phase

*Clear it by:* rotating `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`,
`SESSION_SIGNING_SECRET`, `TELEGRAM_WEBHOOK_SECRET`, and
`INTERNAL_MONITORING_TOKEN` at the invite-only → public boundary.

## Accepted limitations — ship with these, but say so

- **Reminder punctuality is best-effort.** The keep-alive layers make on-time
  delivery likely, not guaranteed. If a reminder is missed, a user who relies
  on it is genuinely let down. Either set expectations in `/start`, or move to
  an always-on instance before promising punctuality.
- **Nutrition figures are model estimates.** Fine for rough tracking, not for
  anyone making medical decisions. The bot already presents them as
  approximate; keep it that way.
- **Editing a food draft item by item still needs the Mini App.**
- **No load test has been run.** Unknown behaviour above a handful of
  concurrent users.
- **No backup or restore drill.** If the Neon database is lost, the recovery
  path is untested.

## What is genuinely solid

Not everything needs work. These have been checked and hold up:

- **Tenant isolation.** `owner_id` comes from the authenticated Telegram
  identity and is never accepted from model output or client payloads.
  Listing, search, reference resolution, and candidate selection are all
  owner-scoped, with cross-tenant tests on each.
- **Direct messages only.** Any non-private chat is refused before a record is
  read or written. This closes the one failure mode that would have exposed a
  user's records to other people.
- **Model output is untrusted.** Strict Pydantic unions reject extra fields,
  identity fields, hidden reasoning, invalid money, and malformed shapes.
  Nothing outside the allow-list can execute.
- **Writes are confirmed; reads are not.** Deletion always confirms, and a
  disambiguation choice is honoured only if it matches a candidate the server
  itself offered.
- **Prompt injection is contained** by the schema rather than by instructions.

## Ordered checklist

### Phase 1 — prove it works at all
- [ ] Push `public-v2`; confirm Render deploys the new commit.
- [ ] `/ready`: status ready, `migration_revision: j5f7b9c1e3a4`,
      `keep_alive: running`.
- [ ] Run the voice capability test plan end to end.
- [ ] Fix whatever it finds. Re-run the failed phases.

### Phase 2 — make failure visible
- [ ] Set `SENTRY_DSN`.
- [ ] Alerting uptime monitor on `/ready`.
- [ ] Second external keep-alive pinger (see `docs/KEEP_ALIVE.md`).
- [ ] Watch Groq usage and the provider-fallback log lines for a week of real
      use.

### Phase 3 — survive strangers
- [ ] Privacy policy published and linked.
- [ ] Decide the behaviour at provider capacity.
- [ ] Rotate all secrets.
- [ ] Backup/restore drill against a disposable database.
- [ ] Invite 5-10 people who are not you. Watch what they say to it — the
      intent model has only ever heard one person's phrasing.

### Phase 4 — open the doors
- [ ] BotFather: final name, username, description, about text, profile
      picture, Mini App menu button.
- [ ] BotFather `/setprivacy` → **Enabled**.
- [ ] Confirm the command menu published by `setMyCommands` looks right.
- [ ] Set `INVITE_ONLY=false`.

## The honest recommendation

Phase 1 and Phase 3's small closed beta are where the real information is.
Everything in this repository is currently an untested hypothesis about how
people will talk to the bot. The intent model has been tuned against one
person's phrasing and a synthetic evaluation corpus.

Do not skip the closed beta with people who are not you. That is where you
learn whether "show me all my notes" was the only phrasing that mattered, or
whether ten other phrasings fail. It costs a week and it is the difference
between shipping something good and shipping something that merely passes its
own tests.
