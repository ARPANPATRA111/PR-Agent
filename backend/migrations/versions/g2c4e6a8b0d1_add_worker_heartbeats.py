"""Add content-free worker heartbeat state.

Revision ID: g2c4e6a8b0d1
Revises: f8b1d4e7a2c6
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "g2c4e6a8b0d1"
down_revision: Union[str, None] = "f8b1d4e7a2c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("worker_name", sa.String(length=64), nullable=False),
        sa.Column("instance_id", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "started_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "processed_total",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_error_category", sa.String(length=64)),
        sa.CheckConstraint(
            "status IN ('starting', 'running', 'stopping', 'failed')",
            name=op.f("ck_worker_heartbeats_status_supported"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_heartbeats")),
        sa.UniqueConstraint(
            "worker_name",
            "instance_id",
            name=op.f("uq_worker_heartbeats_worker_instance"),
        ),
    )
    op.create_index(
        "ix_worker_heartbeats_worker_name_last_seen_at_utc",
        "worker_heartbeats",
        ["worker_name", "last_seen_at_utc"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_heartbeats_worker_name_last_seen_at_utc",
        table_name="worker_heartbeats",
    )
    op.drop_table("worker_heartbeats")
