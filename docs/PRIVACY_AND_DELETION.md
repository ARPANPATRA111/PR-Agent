# Privacy and deletion

Records are tenant-owned and queried through authenticated internal owner IDs.
Users can export their own work logs, notes, money entries, goals, reminders,
nutrition data, and preferences as JSON or a CSV zip.

Account deletion requires recent Telegram authentication and explicit typed
confirmation. It cancels future reminders and digests, removes public records,
legacy tenant records and search copies, revokes sessions, and leaves only a
pseudonymous deletion audit. Individual record deletion also clears bounded
agent references to that record; current summaries are calculated from live
records and therefore stop including it.

Processed Telegram message identifiers may be queued for best-effort deletion
when cleanup is enabled. Cleanup stores no message body, is retried separately,
and cannot roll back application data. Expired sessions, update receipts,
delivery payload snapshots, and completed cleanup metadata are pruned by the
retention worker.
