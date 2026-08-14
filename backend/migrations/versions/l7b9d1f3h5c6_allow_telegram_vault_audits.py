"""allow telegram vault audits

Revision ID: l7b9d1f3h5c6
Revises: k6a8c0e2g4b5
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "l7b9d1f3h5c6"
down_revision: Union[str, None] = "k6a8c0e2g4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("private_fact_audits") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_private_fact_audits_channel_supported"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_private_fact_audits_channel_supported"),
            "channel IN ('mini_app', 'telegram')",
        )


def downgrade() -> None:
    with op.batch_alter_table("private_fact_audits") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_private_fact_audits_channel_supported"),
            type_="check",
        )
        batch_op.create_check_constraint(
            op.f("ck_private_fact_audits_channel_supported"),
            "channel = 'mini_app'",
        )
