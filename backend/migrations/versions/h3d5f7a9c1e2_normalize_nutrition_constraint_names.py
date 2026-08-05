"""Normalize nutrition check-constraint names.

Revision ID: h3d5f7a9c1e2
Revises: g2c4e6a8b0d1
Create Date: 2026-08-05
"""

from typing import Sequence, Union

from alembic import op

revision: str = "h3d5f7a9c1e2"
down_revision: Union[str, None] = "g2c4e6a8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINTS = (
    (
        "nutrition_logs",
        "ck_nutrition_logs_ck_nutrition_logs_status_supported",
        "ck_nutrition_logs_status_supported",
        "status IN ('draft', 'confirmed', 'unestimated')",
    ),
    (
        "user_preferences",
        "ck_user_preferences_ck_user_preferences_milk_serving_supported",
        "ck_user_preferences_milk_serving_supported",
        "default_milk_serving_ml > 0 AND default_milk_serving_ml <= 5000",
    ),
    (
        "user_preferences",
        "ck_user_preferences_ck_user_preferences_measurement_system_supported",
        "ck_user_preferences_measurement_system_supported",
        "measurement_system IN ('metric', 'imperial')",
    ),
)

POSTGRES_MEASUREMENT_NAME = (
    "ck_user_preferences_ck_user_preferences_measurement_sys_5c80"
)


def _database_name(name: str) -> str:
    if (
        op.get_bind().dialect.name == "postgresql"
        and name
        == "ck_user_preferences_ck_user_preferences_measurement_system_supported"
    ):
        return POSTGRES_MEASUREMENT_NAME
    return name


def _replace_constraint(
    table_name: str,
    old_name: str,
    new_name: str,
    expression: str,
) -> None:
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_constraint(op.f(old_name), type_="check")
        batch_op.create_check_constraint(op.f(new_name), expression)


def upgrade() -> None:
    for table_name, old_name, new_name, expression in CONSTRAINTS:
        _replace_constraint(
            table_name,
            _database_name(old_name),
            new_name,
            expression,
        )


def downgrade() -> None:
    for table_name, old_name, new_name, expression in reversed(CONSTRAINTS):
        _replace_constraint(
            table_name,
            new_name,
            _database_name(old_name),
            expression,
        )
