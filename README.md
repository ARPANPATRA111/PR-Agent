<p align="center">
  <img src="frontend/public/pr-agent-welcome.png" width="860" alt="PR-Agent voice-first personal tracker">
</p>

<h1 align="center">PR-Agent</h1>

<p align="center">
  A privacy-first Telegram companion for tracking work, money, notes, reminders, goals, nutrition, and important personal facts by text or voice.
</p>

<p align="center">
  <a href="https://t.me/Arpan_1_bot?start=public"><strong>Open PR-Agent in Telegram</strong></a>
  ·
  <a href="https://excited-dolphin-ec9.notion.site/PR-Agent-progress-report-agent-3c4f42f3d9fb80af94c3d94683c44a33?source=copy_link">Build notes</a>
</p>

## What it does

- Captures text or voice as work logs, notes, expenses, income, goals, reminders, or meals.
- Tracks Indian household foods with visible calorie and protein assumptions.
- Answers date-aware spending and activity questions from the user's own history.
- Provides a Telegram Mini App for reviewing, filtering, editing, and deleting records.
- Supports an optional encrypted, masked, confirmation-gated vault for personal facts.

```mermaid
flowchart LR
    T[Telegram text or voice] --> A[FastAPI bounded assistant]
    M[Telegram Mini App] --> A
    A --> S[(Supabase PostgreSQL)]
    A --> G[Groq transcription and intent]
```

Every query and mutation is scoped server-side to the authenticated Telegram owner. Voice audio is not retained after transcription. Natural-language text and voice share a 25-request daily allowance; once reached, voice is rejected before transcription. Deterministic slash commands remain available.

## Try it

These exact forms work without follow-up questions:

```text
/log Finished release testing
/note Submit scholarship form
/expense 240 INR dinner
```

<table align="center">
  <tr>
    <td align="center" width="50%">
      <img src="frontend/public/Bot_pfp.png" width="220" alt="PR-Agent bot profile">
      <br><sub>Speak or type. PR-Agent keeps the record structured.</sub>
    </td>
    <td align="center" width="50%">
      <a href="https://t.me/Arpan_1_bot?start=public">
        <img src="frontend/public/bot-qr.png" width="220" alt="Scan to open PR-Agent on Telegram">
      </a>
      <br><sub>Scan to start, then pin the chat so it stays easy to find.</sub>
    </td>
  </tr>
</table>

## Release checks

| Scenario tested | Outcome |
|---|---|
| A second user attempts to read, edit, or delete another user's record | Denied; no cross-user data returned |
| A user reaches the 25-request allowance and sends another voice note | Rejected before transcription is called |
| Mini App authentication and CRUD run on a Telegram-sized mobile viewport | Passed, including validation, nutrition totals, and session expiry |
| Spending is queried by period, search term, and highest category | Correct period and ranking returned; empty periods remain empty |
| Indian meal variants and user-supplied calories/protein are logged | Distinct estimates preserved; vague portions require review |

Verified locally on 23 August 2026: 345 backend tests, 12 frontend tests, and 6 mobile browser flows passed; lint, type-check, and production build also passed.

## Technical notes

- Backend: FastAPI, SQLAlchemy, Alembic
- Frontend: Next.js, React, TypeScript, Tailwind CSS
- Data: Supabase PostgreSQL
- Delivery: Telegram Bot API, webhook processing, scheduled workers
- Validation: pytest, Vitest, Playwright

## Run locally

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The Mini App must be opened inside Telegram so its signed launch data can be verified. Never commit tokens, database URLs, exports, or encryption keys.

## License

MIT
