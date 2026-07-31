"""Add durable delivery leases and retry state.

Revision ID: d6f4b2c8e1a0
Revises: c24f619ecae7
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d6f4b2c8e1a0"
down_revision: Union[str, None] = "c24f619ecae7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


DELIVERY_STATUSES = (
    "status IN " "('pending', 'claimed', 'sent', 'failed', 'dead_letter', 'cancelled')"
)


def upgrade() -> None:
    with op.batch_alter_table("reminders") as batch_op:
        batch_op.create_index(
            "ix_reminders_enabled_next_run_at_utc",
            ["enabled", "next_run_at_utc"],
            unique=False,
        )

    with op.batch_alter_table("reminder_deliveries") as batch_op:
        batch_op.add_column(
            sa.Column("next_attempt_at_utc", sa.DateTime(timezone=True))
        )
        batch_op.add_column(sa.Column("claimed_at_utc", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("lease_expires_at_utc", sa.DateTime(timezone=True))
        )
        batch_op.add_column(sa.Column("telegram_message_id", sa.BigInteger()))
        batch_op.drop_constraint(
            batch_op.f("ck_reminder_deliveries_status_supported"),
            type_="check",
        )
        batch_op.create_check_constraint(
            "status_supported",
            DELIVERY_STATUSES,
        )
        batch_op.create_index(
            "ix_reminder_deliveries_status_next_attempt_at_utc",
            ["status", "next_attempt_at_utc"],
            unique=False,
        )

    with op.batch_alter_table("scheduled_digests") as batch_op:
        batch_op.create_index(
            "ix_scheduled_digests_enabled_next_run_at_utc",
            ["enabled", "next_run_at_utc"],
            unique=False,
        )

    with op.batch_alter_table("digest_deliveries") as batch_op:
        batch_op.add_column(sa.Column("scheduled_digest_id", sa.Integer()))
        batch_op.add_column(
            sa.Column(
                "scheduled_occurrence_at_utc",
                sa.DateTime(timezone=True),
            )
        )
        batch_op.add_column(
            sa.Column(
                "attempt_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("next_attempt_at_utc", sa.DateTime(timezone=True))
        )
        batch_op.add_column(sa.Column("claimed_at_utc", sa.DateTime(timezone=True)))
        batch_op.add_column(
            sa.Column("lease_expires_at_utc", sa.DateTime(timezone=True))
        )
        batch_op.add_column(sa.Column("telegram_message_id", sa.BigInteger()))
        batch_op.add_column(sa.Column("message_text", sa.Text()))
        batch_op.add_column(sa.Column("payload_snapshot", sa.JSON()))

    op.execute(sa.text("""
            INSERT INTO scheduled_digests
                (owner_id, timezone, weekday, scheduled_local_time, enabled)
            SELECT DISTINCT
                dd.owner_id,
                COALESCE(up.timezone, 'UTC'),
                6,
                '20:00:00',
                false
            FROM digest_deliveries AS dd
            LEFT JOIN user_preferences AS up ON up.owner_id = dd.owner_id
            WHERE NOT EXISTS (
                SELECT 1
                FROM scheduled_digests AS sd
                WHERE sd.owner_id = dd.owner_id
            )
            """))
    op.execute(sa.text("""
            UPDATE digest_deliveries
            SET scheduled_digest_id = (
                    SELECT sd.id
                    FROM scheduled_digests AS sd
                    WHERE sd.owner_id = digest_deliveries.owner_id
                ),
                scheduled_occurrence_at_utc = COALESCE(
                    delivered_at_utc,
                    created_at
                )
            """))

    with op.batch_alter_table("digest_deliveries") as batch_op:
        batch_op.alter_column(
            "scheduled_digest_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "scheduled_occurrence_at_utc",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_digest_deliveries_scheduled_digest_id_scheduled_digests"),
            "scheduled_digests",
            ["scheduled_digest_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_check_constraint(
            "status_supported",
            DELIVERY_STATUSES,
        )
        batch_op.create_check_constraint(
            "attempt_count_nonnegative",
            "attempt_count >= 0",
        )
        batch_op.create_index(
            "ix_digest_deliveries_status_next_attempt_at_utc",
            ["status", "next_attempt_at_utc"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("digest_deliveries") as batch_op:
        batch_op.drop_index("ix_digest_deliveries_status_next_attempt_at_utc")
        batch_op.drop_constraint(
            batch_op.f("ck_digest_deliveries_attempt_count_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_digest_deliveries_status_supported"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("fk_digest_deliveries_scheduled_digest_id_scheduled_digests"),
            type_="foreignkey",
        )
        batch_op.drop_column("payload_snapshot")
        batch_op.drop_column("message_text")
        batch_op.drop_column("telegram_message_id")
        batch_op.drop_column("lease_expires_at_utc")
        batch_op.drop_column("claimed_at_utc")
        batch_op.drop_column("next_attempt_at_utc")
        batch_op.drop_column("attempt_count")
        batch_op.drop_column("scheduled_occurrence_at_utc")
        batch_op.drop_column("scheduled_digest_id")

    with op.batch_alter_table("scheduled_digests") as batch_op:
        batch_op.drop_index("ix_scheduled_digests_enabled_next_run_at_utc")

    with op.batch_alter_table("reminder_deliveries") as batch_op:
        batch_op.drop_index("ix_reminder_deliveries_status_next_attempt_at_utc")
        batch_op.drop_constraint(
            batch_op.f("ck_reminder_deliveries_status_supported"),
            type_="check",
        )
        batch_op.create_check_constraint(
            "status_supported",
            "status IN ('pending', 'claimed', 'sent', 'failed', 'cancelled')",
        )
        batch_op.drop_column("telegram_message_id")
        batch_op.drop_column("lease_expires_at_utc")
        batch_op.drop_column("claimed_at_utc")
        batch_op.drop_column("next_attempt_at_utc")

    with op.batch_alter_table("reminders") as batch_op:
        batch_op.drop_index("ix_reminders_enabled_next_run_at_utc")
