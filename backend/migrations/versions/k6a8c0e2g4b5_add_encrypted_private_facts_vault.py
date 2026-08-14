"""add encrypted private facts vault

Revision ID: k6a8c0e2g4b5
Revises: j5f7b9c1e3a4
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "k6a8c0e2g4b5"
down_revision: Union[str, None] = "j5f7b9c1e3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "private_facts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("record_uuid", sa.String(length=36), nullable=False),
        sa.Column("fact_type", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("masked_value", sa.String(length=64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.String(length=32), nullable=False),
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
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "fact_type IN ('aadhaar_last4', 'phone', 'bank_account', 'ifsc', "
            "'academic_score', 'other_permitted')",
            name=op.f("ck_private_facts_fact_type_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["app_users.id"],
            name=op.f("fk_private_facts_owner_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_private_facts")),
        sa.UniqueConstraint("record_uuid", name=op.f("uq_private_facts_record_uuid")),
    )
    with op.batch_alter_table("private_facts") as batch_op:
        batch_op.create_index(
            "ix_private_facts_owner_id_created_at",
            ["owner_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_private_facts_owner_id_fact_type",
            ["owner_id", "fact_type"],
            unique=False,
        )

    op.create_table(
        "private_fact_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("record_uuid", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "channel", sa.String(length=24), server_default="mini_app", nullable=False
        ),
        sa.Column(
            "occurred_at_utc",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'reveal', 'delete')",
            name=op.f("ck_private_fact_audits_action_supported"),
        ),
        sa.CheckConstraint(
            "channel = 'mini_app'",
            name=op.f("ck_private_fact_audits_channel_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["app_users.id"],
            name=op.f("fk_private_fact_audits_owner_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_private_fact_audits")),
    )
    with op.batch_alter_table("private_fact_audits") as batch_op:
        batch_op.create_index(
            "ix_private_fact_audits_owner_id_occurred_at_utc",
            ["owner_id", "occurred_at_utc"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("private_fact_audits") as batch_op:
        batch_op.drop_index("ix_private_fact_audits_owner_id_occurred_at_utc")
    op.drop_table("private_fact_audits")
    with op.batch_alter_table("private_facts") as batch_op:
        batch_op.drop_index("ix_private_facts_owner_id_fact_type")
        batch_op.drop_index("ix_private_facts_owner_id_created_at")
    op.drop_table("private_facts")
