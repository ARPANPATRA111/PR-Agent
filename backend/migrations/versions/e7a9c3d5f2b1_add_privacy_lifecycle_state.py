"""Add privacy lifecycle and Telegram cleanup state.

Revision ID: e7a9c3d5f2b1
Revises: d6f4b2c8e1a0
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7a9c3d5f2b1"
down_revision: Union[str, None] = "d6f4b2c8e1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "account_deletion_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deletion_id", sa.String(length=64), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "deleted_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "legacy_rows_removed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_account_deletion_audits"),
        ),
        sa.UniqueConstraint(
            "deletion_id",
            name=op.f("uq_account_deletion_audits_deletion_id"),
        ),
        sa.UniqueConstraint(
            "identity_hash",
            name=op.f("uq_account_deletion_audits_identity_hash"),
        ),
    )

    with op.batch_alter_table("telegram_messages") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cleanup_status",
                sa.String(length=24),
                server_default="pending",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "cleanup_attempt_count",
                sa.Integer(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "next_cleanup_attempt_at_utc",
                sa.DateTime(timezone=True),
            )
        )
        batch_op.add_column(
            sa.Column("cleanup_claimed_at_utc", sa.DateTime(timezone=True))
        )
        batch_op.add_column(
            sa.Column(
                "cleanup_lease_expires_at_utc",
                sa.DateTime(timezone=True),
            )
        )
        batch_op.add_column(sa.Column("cleanup_error_category", sa.String(length=64)))
        batch_op.create_check_constraint(
            "cleanup_status_supported",
            "cleanup_status IN "
            "('pending', 'claimed', 'deleted', 'failed', "
            "'dead_letter', 'cancelled')",
        )
        batch_op.create_check_constraint(
            "cleanup_attempt_count_nonnegative",
            "cleanup_attempt_count >= 0",
        )
        batch_op.create_index(
            "ix_telegram_messages_cleanup_status_next_attempt",
            ["cleanup_status", "next_cleanup_attempt_at_utc"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("telegram_messages") as batch_op:
        batch_op.drop_index("ix_telegram_messages_cleanup_status_next_attempt")
        batch_op.drop_constraint(
            batch_op.f("ck_telegram_messages_cleanup_attempt_count_nonnegative"),
            type_="check",
        )
        batch_op.drop_constraint(
            batch_op.f("ck_telegram_messages_cleanup_status_supported"),
            type_="check",
        )
        batch_op.drop_column("cleanup_error_category")
        batch_op.drop_column("cleanup_lease_expires_at_utc")
        batch_op.drop_column("cleanup_claimed_at_utc")
        batch_op.drop_column("next_cleanup_attempt_at_utc")
        batch_op.drop_column("cleanup_attempt_count")
        batch_op.drop_column("cleanup_status")

    op.drop_table("account_deletion_audits")
