"""Require nutrition confirmation for existing and future accounts.

Revision ID: m8c0e2g4i6d7
Revises: l7b9d1f3h5c6
Create Date: 2026-08-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "m8c0e2g4i6d7"
down_revision: Union[str, None] = "l7b9d1f3h5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE user_preferences "
            "SET nutrition_confirmation_required = true "
            "WHERE nutrition_confirmation_required = false"
        )
    )


def downgrade() -> None:
    # This is a preference default/data correction. Reverting every true value
    # would overwrite choices users made independently, so downgrade is a safe
    # no-op.
    pass
