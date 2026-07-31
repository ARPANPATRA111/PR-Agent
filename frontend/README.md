# PR-Agent Mini App

This Next.js 16 application is the mobile-first Telegram Mini App for public-v2.
It authenticates only with Telegram-signed `initData`; it has no typed Telegram
ID or password fallback.

The UI supports tenant-scoped create, list, edit, and delete flows for work
logs, notes, reminders, ledger entries, goals, and nutrition, plus settings,
exports, and account deletion. It does not expose legacy reports or LinkedIn
generation.

```powershell
corepack enable
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm test:e2e
```

Set `NEXT_PUBLIC_API_URL` to the matching API origin at build time. Production
users must launch the Mini App through Telegram.
