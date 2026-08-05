"""Allow completed worker heartbeats to use the stopped state.

Revision ID: i4e6a8b0d2f3
Revises: h3d5f7a9c1e2
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "i4e6a8b0d2f3"
down_revision: Union[str, None] = "h3d5f7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "ck_worker_heartbeats_status_supported"
ACTIVE_STATES = "status IN ('starting', 'running', 'stopping', 'failed')"
ALL_STATES = "status IN ('starting', 'running', 'stopping', 'stopped', 'failed')"


def _replace_status_constraint(expression: str) -> None:
    with op.batch_alter_table("worker_heartbeats") as batch_op:
        batch_op.drop_constraint(op.f(CONSTRAINT_NAME), type_="check")
        batch_op.create_check_constraint(op.f(CONSTRAINT_NAME), expression)


def upgrade() -> None:
    _replace_status_constraint(ALL_STATES)


def downgrade() -> None:
    _replace_status_constraint(ACTIVE_STATES)
