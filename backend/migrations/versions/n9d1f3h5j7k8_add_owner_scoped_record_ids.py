"""Add stable owner-scoped identifiers for user-visible records.

Revision ID: n9d1f3h5j7k8
Revises: m8c0e2g4i6d7
Create Date: 2026-08-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "n9d1f3h5j7k8"
down_revision: Union[str, None] = "m8c0e2g4i6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


RECORD_TABLES = (
    ("work_logs", "work_log"),
    ("notes", "note"),
    ("ledger_entries", "ledger_entry"),
    ("nutrition_logs", "nutrition_log"),
)


def upgrade() -> None:
    op.create_table(
        "owner_record_counters",
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("last_value", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint(
            "last_value >= 0",
            name=op.f("ck_owner_record_counters_last_value_nonnegative"),
        ),
        sa.CheckConstraint(
            "record_type IN ('work_log', 'note', 'ledger_entry', 'nutrition_log')",
            name=op.f("ck_owner_record_counters_record_type_supported"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["app_users.id"],
            name=op.f("fk_owner_record_counters_owner_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "owner_id",
            "record_type",
            name=op.f("pk_owner_record_counters"),
        ),
    )

    for table_name, _ in RECORD_TABLES:
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.add_column(sa.Column("public_id", sa.Integer(), nullable=True))
        # Global ids are creation-ordered. Counting only earlier ids within the
        # same owner yields a deterministic 1..N backfill without exposing the
        # global sequence after this migration.
        op.execute(
            sa.text(
                f"UPDATE {table_name} AS current_row "
                "SET public_id = ("
                f"SELECT COUNT(*) FROM {table_name} AS earlier "
                "WHERE earlier.owner_id = current_row.owner_id "
                "AND earlier.id <= current_row.id)"
            )
        )
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column(
                "public_id",
                existing_type=sa.Integer(),
                nullable=False,
            )
            batch_op.create_unique_constraint(
                op.f(f"uq_{table_name}_owner_id_public_id"),
                ["owner_id", "public_id"],
            )

    for table_name, record_type in RECORD_TABLES:
        op.execute(
            sa.text(
                "INSERT INTO owner_record_counters "
                "(owner_id, record_type, last_value) "
                f"SELECT owner_id, '{record_type}', MAX(public_id) "
                f"FROM {table_name} GROUP BY owner_id"
            )
        )


def downgrade() -> None:
    for table_name, _ in reversed(RECORD_TABLES):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(
                op.f(f"uq_{table_name}_owner_id_public_id"),
                type_="unique",
            )
            batch_op.drop_column("public_id")
    op.drop_table("owner_record_counters")
