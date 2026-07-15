"""create portal tables: projects, cost_config, dev_licenses

Revision ID: 0001
Revises:
Create Date: 2026-06-03 16:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portal_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("color", sa.String(7), nullable=False, server_default="#6366f1"),
        sa.Column("budget_monthly", sa.Float, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        "portal_cost_config",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("model_name", sa.String(60), nullable=False, unique=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("price_input_mtok", sa.Float, nullable=False, server_default="0"),
        sa.Column("price_output_mtok", sa.Float, nullable=False, server_default="0"),
        sa.Column("price_cache_read_mtok", sa.Float, nullable=False, server_default="0"),
        sa.Column("price_cache_creation_mtok", sa.Float, nullable=False, server_default="0"),
        sa.Column("price_per_1k_pages", sa.Float, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_table(
        "portal_dev_licenses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("provider", sa.String(60), nullable=False),
        sa.Column("plan", sa.String(60), nullable=False),
        sa.Column("cost_monthly_usd", sa.Float, nullable=False),
        sa.Column("assignee", sa.String(120), nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("notes", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("portal_dev_licenses")
    op.drop_table("portal_cost_config")
    op.drop_table("portal_projects")
