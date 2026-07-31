"""Dry-run-first additive legacy backfill for public-v2.

This script never deletes or updates a legacy row. Re-running ``--apply`` is
idempotent because public users are unique by Telegram ID and work logs are
unique by ``legacy_raw_entry_id``.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import Session


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from config import settings  # noqa: E402
from public_models import PublicUser, WorkLog  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit additive mappings. Without this flag all writes roll back.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Explicit acknowledgement required for a production connection.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if settings.app_env == "production" and not args.allow_production:
        raise SystemExit(
            "Refusing production database. Use staging first; "
            "--allow-production is required for a reviewed production run."
        )

    engine = create_engine(settings.active_database_url, pool_pre_ping=True)
    table_names = set(inspect(engine).get_table_names())
    required = {"users", "raw_entries", "app_users", "work_logs"}
    missing = sorted(required - table_names)
    if missing:
        raise SystemExit(
            "Migration/backfill prerequisites missing: " + ", ".join(missing)
        )

    legacy_metadata = MetaData()
    legacy_users = Table("users", legacy_metadata, autoload_with=engine)
    legacy_entries = Table("raw_entries", legacy_metadata, autoload_with=engine)

    counters = {
        "legacy_users": 0,
        "users_created": 0,
        "legacy_entries": 0,
        "work_logs_created": 0,
        "work_logs_existing": 0,
    }
    samples: list[str] = []

    with Session(engine) as session:
        user_rows = session.execute(select(legacy_users)).mappings().all()
        counters["legacy_users"] = len(user_rows)
        owner_by_telegram: dict[int, PublicUser] = {}
        for row in user_rows:
            telegram_id = int(row["telegram_id"])
            public_user = session.query(PublicUser).filter_by(
                telegram_id=telegram_id
            ).one_or_none()
            if public_user is None:
                public_user = PublicUser(
                    telegram_id=telegram_id,
                    username=row.get("username"),
                    first_name=row.get("first_name") or "User",
                    last_name=row.get("last_name"),
                )
                session.add(public_user)
                session.flush()
                counters["users_created"] += 1
            owner_by_telegram[telegram_id] = public_user

        entry_rows = session.execute(select(legacy_entries)).mappings().all()
        counters["legacy_entries"] = len(entry_rows)
        for row in entry_rows:
            legacy_id = int(row["id"])
            existing = session.query(WorkLog.id).filter_by(
                legacy_raw_entry_id=legacy_id
            ).scalar()
            if existing is not None:
                counters["work_logs_existing"] += 1
                continue

            telegram_id = int(row["telegram_id"])
            owner = owner_by_telegram.get(telegram_id)
            if owner is None:
                raise RuntimeError(
                    f"Legacy entry {legacy_id} has no legacy user mapping"
                )
            timestamp = row["timestamp"]
            preferences = next(
                (
                    candidate.get("preferences") or {}
                    for candidate in user_rows
                    if int(candidate["telegram_id"]) == telegram_id
                ),
                {},
            )
            timezone_name = preferences.get("timezone", "UTC")
            work_log = WorkLog(
                owner_id=owner.id,
                original_text=row.get("transcript") or "",
                cleaned_text=row.get("transcript") or "",
                logged_at_utc=timestamp,
                user_local_date=timestamp.date(),
                timezone=timezone_name,
                capture_source="legacy_voice",
                voice_file_id=row.get("audio_file_id"),
                legacy_raw_entry_id=legacy_id,
            )
            session.add(work_log)
            counters["work_logs_created"] += 1
            if len(samples) < 5:
                samples.append(
                    f"raw_entries:{legacy_id} -> work_logs:new "
                    f"(owner telegram_id={telegram_id})"
                )

        session.flush()
        mapped_count = session.query(WorkLog).filter(
            WorkLog.legacy_raw_entry_id.is_not(None)
        ).count()
        if mapped_count < counters["legacy_entries"]:
            raise RuntimeError(
                f"Backfill validation failed: {mapped_count} mapped for "
                f"{counters['legacy_entries']} legacy entries"
            )

        if args.apply:
            session.commit()
        else:
            session.rollback()

    mode = "APPLIED" if args.apply else "DRY RUN (rolled back)"
    print(mode)
    for key, value in counters.items():
        print(f"{key}: {value}")
    print(f"validated_mapped_rows: {mapped_count}")
    for sample in samples:
        print(f"sample: {sample}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
