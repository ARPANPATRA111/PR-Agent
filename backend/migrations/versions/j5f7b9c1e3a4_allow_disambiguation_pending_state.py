"""Allow a pending action to wait on the user choosing between records.

Deleting by spoken reference ("my note about the invoice") can match more than
one record. The assistant then offers the candidates and waits, which needs a
pending state distinct from clarification and confirmation.

Revision ID: j5f7b9c1e3a4
Revises: i4e6a8b0d2f3
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "j5f7b9c1e3a4"
down_revision: Union[str, None] = "i4e6a8b0d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PENDING_CONSTRAINT = "ck_agent_pending_actions_state_supported"
PREVIOUS_STATES = (
    "state IN ('clarification', 'confirmation', 'executed', "
    "'cancelled', 'expired')"
)
ALL_STATES = (
    "state IN ('clarification', 'confirmation', 'disambiguation', "
    "'executed', 'cancelled', 'expired')"
)

RUN_CONSTRAINT = "ck_agent_runs_status_supported"
PREVIOUS_RUN_STATUSES = (
    "status IN ('processing', 'completed', 'clarification', "
    "'confirmation', 'rejected', 'failed')"
)
ALL_RUN_STATUSES = (
    "status IN ('processing', 'completed', 'clarification', "
    "'confirmation', 'disambiguation', 'rejected', 'failed')"
)


def _replace_constraint(table: str, name: str, expression: str) -> None:
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_constraint(op.f(name), type_="check")
        batch_op.create_check_constraint(op.f(name), expression)


def upgrade() -> None:
    _replace_constraint("agent_pending_actions", PENDING_CONSTRAINT, ALL_STATES)
    # A run mirrors the state of the pending action it produced.
    _replace_constraint("agent_runs", RUN_CONSTRAINT, ALL_RUN_STATUSES)


def downgrade() -> None:
    # Rows still waiting on a choice would violate the narrower constraints, so
    # resolve them before restoring those. Nothing was deleted for those rows,
    # and the user can simply ask again.
    op.execute(
        "UPDATE agent_pending_actions SET state = 'cancelled' "
        "WHERE state = 'disambiguation'"
    )
    op.execute(
        "UPDATE agent_runs SET status = 'rejected' WHERE status = 'disambiguation'"
    )
    _replace_constraint("agent_runs", RUN_CONSTRAINT, PREVIOUS_RUN_STATUSES)
    _replace_constraint("agent_pending_actions", PENDING_CONSTRAINT, PREVIOUS_STATES)
