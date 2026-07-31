"""Add optimistic concurrency versions to public records.

Revision ID: b783f5d11b0e
Revises: a509623c6959
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b783f5d11b0e"
down_revision: Union[str, None] = "a509623c6959"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "user_preferences",
    "work_logs",
    "notes",
    "reminders",
    "reminder_deliveries",
    "ledger_entries",
    "nutrition_logs",
    "nutrition_items",
    "tracked_goals",
    "telegram_messages",
    "invite_codes",
    "scheduled_digests",
    "digest_deliveries",
    "account_export_requests",
)


def upgrade() -> None:
    for table_name in TABLES:
        op.add_column(
            table_name,
            sa.Column(
                "version",
                sa.Integer(),
                server_default=sa.text("1"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table_name in reversed(TABLES):
        op.drop_column(table_name, "version")
