"""Add nutrition workflow and preference fields.

Revision ID: c24f619ecae7
Revises: b783f5d11b0e
Create Date: 2026-07-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c24f619ecae7"
down_revision: Union[str, None] = "b783f5d11b0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("user_preferences") as batch_op:
        batch_op.add_column(
            sa.Column(
                "default_milk_serving_ml",
                sa.Numeric(precision=10, scale=2),
                server_default=sa.text("250"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "measurement_system",
                sa.String(length=16),
                server_default="metric",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "nutrition_confirmation_required",
                sa.Boolean(),
                server_default="true",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_user_preferences_milk_serving_supported",
            "default_milk_serving_ml > 0 AND default_milk_serving_ml <= 5000",
        )
        batch_op.create_check_constraint(
            "ck_user_preferences_measurement_system_supported",
            "measurement_system IN ('metric', 'imperial')",
        )

    with op.batch_alter_table("nutrition_logs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=16),
                server_default="draft",
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "visible_assumptions",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column(
                "provider_metadata",
                sa.JSON(),
                server_default=sa.text("'{}'"),
                nullable=False,
            )
        )
        batch_op.add_column(
            sa.Column("clarification_question", sa.Text(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_nutrition_logs_status_supported",
            "status IN ('draft', 'confirmed', 'unestimated')",
        )

    with op.batch_alter_table("nutrition_items") as batch_op:
        batch_op.add_column(
            sa.Column(
                "visible_assumptions",
                sa.JSON(),
                server_default=sa.text("'[]'"),
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("nutrition_items") as batch_op:
        batch_op.drop_column("visible_assumptions")
    with op.batch_alter_table("nutrition_logs") as batch_op:
        batch_op.drop_constraint(
            "ck_nutrition_logs_status_supported",
            type_="check",
        )
        batch_op.drop_column("clarification_question")
        batch_op.drop_column("provider_metadata")
        batch_op.drop_column("visible_assumptions")
        batch_op.drop_column("status")
    with op.batch_alter_table("user_preferences") as batch_op:
        batch_op.drop_constraint(
            "ck_user_preferences_measurement_system_supported",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_user_preferences_milk_serving_supported",
            type_="check",
        )
        batch_op.drop_column("nutrition_confirmation_required")
        batch_op.drop_column("measurement_system")
        batch_op.drop_column("default_milk_serving_ml")
