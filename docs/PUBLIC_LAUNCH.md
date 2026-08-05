# Public launch checklist

What the code now handles, and what still has to be done by hand before
`INVITE_ONLY` is turned off.

## Already enforced in code

- **Direct messages only.** Any non-private chat is refused before a record is
  read or written, and a button tapped in a group resolves nothing. Everything
  this bot stores belongs to one person; in a group the reply — and every
  listing inside it — would be readable by every member.
- **Tenant isolation.** `owner_id` is derived from the authenticated Telegram
  identity and is never accepted from model output or client payloads. Listing,
  searching, reference resolution, and candidate selection are all owner-scoped
  and covered by cross-tenant tests.
- **Per-user quotas plus a deployment-wide ceiling.** See
  `GLOBAL_DAILY_AI_LIMIT` in `docs/BOUNDED_ASSISTANT.md`.
- **Voice billed in 15-second blocks** rather than rounded up to whole minutes.
- **Onboarding.** `/start` leads with the voice gesture and one-line examples,
  states the privacy position, and offers the Mini App as a button.

## Manual steps before going public

### BotFather

- [ ] Set the final bot name and username.
- [ ] `/setdescription` — shown on the empty chat screen before anyone starts.
- [ ] `/setabouttext` — shown on the bot's profile card.
- [ ] `/setuserpic`.
- [ ] `/setprivacy` → **Enabled**. The bot cannot then read ordinary group
      messages at all. The in-code refusal stays as defence in depth.
- [ ] `/setcommands` with a short list only. The full command surface keeps
      working when typed; a new user should not be shown forty commands:

      start - What this bot does
      today - What I did today
      week - This week so far
      spending - Money in and out this month
      notes - My notes
      reminders - My reminders
      settings - Preferences and dashboard
      help - All commands

- [ ] Configure the Mini App menu button.

### Configuration

- [ ] Confirm the tightened quota values in `render.free.yaml` suit expected
      load, and that `GLOBAL_DAILY_AI_LIMIT` matches the actual Groq allowance.
- [ ] Rotate `TELEGRAM_BOT_TOKEN`, `GROQ_API_KEY`, `SESSION_SIGNING_SECRET`,
      `TELEGRAM_WEBHOOK_SECRET`, and `INTERNAL_MONITORING_TOKEN` at the
      invite-only → public boundary.
- [ ] Set `INVITE_ONLY=false` only after everything above is done.

### Legal and privacy

- [ ] Publish a privacy policy and link it from `/start` and the Mini App.
      Voice is sent to a third-party provider for transcription, and the bot
      stores personal financial and health-adjacent data; for users in India
      the DPDP Act consent requirements apply.
- [ ] Document the retention and deletion path (`/export`, `/deleteaccount`)
      in that policy.

### Operations

- [ ] Set up the external keep-alive pinger described in `docs/KEEP_ALIVE.md`,
      including the second non-GitHub pinger.
- [ ] Check Render instance-hours and Neon compute-hours after the first week.
- [ ] Decide what happens when the global ceiling is hit routinely — that is
      the signal to move off the free tier rather than to raise the cap.

## Known gaps to watch after launch

- Reminder punctuality still depends on the process staying awake. The
  keep-alive layers make this likely, not guaranteed.
- Nutrition figures are model estimates, not measurements.
- Voice can create, retrieve, and delete records, but editing an existing
  record, pausing/resuming, updating goal progress, and confirming a nutrition
  draft still need the Mini App or a slash command.
