"""add tax_rate_pct to portal_dev_licenses

Las licencias se daban de alta al precio de tarifa del proveedor (sin impuestos),
pero la factura real llega con el 21% de IVA. Se guarda el tipo por licencia —
no como constante — porque no todas lo llevan: las facturas con inversión del
sujeto pasivo van al 0%.

Las filas existentes se rellenan al 21% (el caso habitual en España); las que no
lleven IVA se corrigen desde /config.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-21 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default rellena las filas ya existentes; se retira acto seguido para
    # que el valor por defecto lo ponga el modelo y no la base de datos.
    op.add_column(
        "portal_dev_licenses",
        sa.Column("tax_rate_pct", sa.Float(), nullable=False, server_default="21.0"),
    )
    op.alter_column("portal_dev_licenses", "tax_rate_pct", server_default=None)


def downgrade() -> None:
    op.drop_column("portal_dev_licenses", "tax_rate_pct")
