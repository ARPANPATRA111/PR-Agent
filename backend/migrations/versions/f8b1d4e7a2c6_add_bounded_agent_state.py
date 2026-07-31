"""Add bounded assistant audit and pending-action state.

Revision ID: f8b1d4e7a2c6
Revises: e7a9c3d5f2b1
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f8b1d4e7a2c6"
down_revision: Union[str, None] = "e7a9c3d5f2b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="processing",
            nullable=False,
        ),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("original_update_id", sa.BigInteger(), nullable=False),
        sa.Column("safe_error_category", sa.String(length=64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at_utc", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'clarification', "
            "'confirmation', 'rejected', 'failed')",
            name=op.f("ck_agent_runs_status_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["app_users.id"],
            name=op.f("fk_agent_runs_owner_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(
        "ix_agent_runs_owner_id_created_at",
        "agent_runs",
        ["owner_id", "created_at"],
    )

    op.create_table(
        "agent_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("record_type", sa.String(length=32)),
        sa.Column("record_id", sa.Integer()),
        sa.Column(
            "argument_fields",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("safe_error_category", sa.String(length=64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at_utc", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('proposed', 'executed', 'clarification', "
            "'confirmation_required', 'rejected', 'failed', 'cancelled')",
            name=op.f("ck_agent_actions_status_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["app_users.id"],
            name=op.f("fk_agent_actions_owner_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_actions_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_actions")),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name=op.f("uq_agent_actions_owner_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_agent_actions_owner_id_created_at",
        "agent_actions",
        ["owner_id", "created_at"],
    )

    op.create_table(
        "agent_pending_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column(
            "proposed_arguments",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "missing_fields",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("prompt", sa.String(length=1000), nullable=False),
        sa.Column("original_update_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("expires_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at_utc", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('clarification', 'confirmation', 'executed', "
            "'cancelled', 'expired')",
            name=op.f("ck_agent_pending_actions_state_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["app_users.id"],
            name=op.f("fk_agent_pending_actions_owner_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_pending_actions_run_id_agent_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_agent_pending_actions"),
        ),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name=op.f("uq_agent_pending_actions_owner_id_idempotency_key"),
        ),
    )
    op.create_index(
        "ix_agent_pending_actions_owner_id_state_expires",
        "agent_pending_actions",
        ["owner_id", "state", "expires_at_utc"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_pending_actions_owner_id_state_expires",
        table_name="agent_pending_actions",
    )
    op.drop_table("agent_pending_actions")
    op.drop_index(
        "ix_agent_actions_owner_id_created_at",
        table_name="agent_actions",
    )
    op.drop_table("agent_actions")
    op.drop_index(
        "ix_agent_runs_owner_id_created_at",
        table_name="agent_runs",
    )
    op.drop_table("agent_runs")
