"""rename project 'Siniestros Fase I' to 'Siniestros Automation'

El proyecto pasa a llamarse "Siniestros Automation" (engloba Fase I + futuras
fases). La imputación de costes se hace bajo ese nombre. La unión con
api_audit_logs sigue siendo por `conversation_table` (siniestro_conversations).

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "Siniestros Fase I"
_NEW = "Siniestros Automation"


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE portal_projects SET name = :new WHERE name = :old").bindparams(
            new=_NEW, old=_OLD
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE portal_projects SET name = :old WHERE name = :new").bindparams(
            new=_NEW, old=_OLD
        )
    )
