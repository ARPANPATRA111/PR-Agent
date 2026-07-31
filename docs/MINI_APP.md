# Telegram Mini App

## Authentication

The frontend reads `Telegram.WebApp.initData` and sends it to
`POST /api/auth/telegram`. The backend verifies Telegram's HMAC signature and
freshness before issuing an HTTP-only session cookie and a CSRF token.

There is no manual Telegram-ID or password login. Opening the web URL outside
Telegram displays a safe retry screen.

## Screens

- Home: today's work, reminders, ledger totals, nutrition, and active goals
- Work: create, browse, edit, and delete work logs
- Notes: create, browse, edit, pin, and delete notes
- Reminders: create, browse, edit, pause/resume, and delete schedules
- Money: create, browse, edit, and delete private income/expense records
- Nutrition: preview, confirm, edit servings, delete, and browse by date
- Goals: create, edit progress, change state, browse, and delete
- Settings: timezone, notification schedule, and nutrition targets
- Export and Account: confirmation-oriented privacy controls

The bottom navigation scrolls horizontally on narrow devices so controls do not
overflow the viewport. All actionable elements are keyboard reachable and have
accessible labels.

## Local validation

```powershell
Set-Location frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm exec playwright install chromium
pnpm test:e2e
pnpm build
```

Browser tests mock the backend at the network boundary and cover:

- valid and invalid Telegram authentication
- work and note CRUD
- reminder and ledger creation
- nutrition confirmation and serving edits
- cross-user record denial
- session expiry, logout, and account-deletion confirmation

Backend authorization tests remain the source of truth for tenant isolation.
