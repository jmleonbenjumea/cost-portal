"""drop conversation_table from portal_projects

La imputación de costes pasa a hacerse por `api_audit_logs.proyecto = Project.name`
(sin JOINs contra la tabla de conversaciones). La columna `conversation_table`
ya no se usa.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-19 00:00:01.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("portal_projects", "conversation_table")


def downgrade() -> None:
    op.add_column(
        "portal_projects",
        sa.Column("conversation_table", sa.String(120), nullable=True),
    )
