# Backup and restore

Use managed PostgreSQL point-in-time recovery or encrypted logical backups.
Backups must be access-controlled, encrypted, retained according to policy, and
stored separately from application credentials.

Before each production migration:

1. Create a provider snapshot or `pg_dump` in the protected operations
   environment.
2. Verify the backup completed and record its checksum or provider identifier.
3. Restore into an isolated staging database.
4. Run `python -m alembic upgrade head`, `/ready`, tenant-isolation tests, an
   export, and a reminder claim/delivery test against the restored copy.
5. Delete the restore environment according to the retention policy.

Example commands intentionally contain placeholders:

```text
pg_dump --format=custom --file=backup.dump <protected-database-url>
createdb <isolated-restore-database>
pg_restore --clean --if-exists --no-owner --dbname=<isolated-restore-url> backup.dump
```

Never run `--clean` against staging or production. A release gate is incomplete
until a real isolated restore has been performed and recorded outside Git.
