"""Portal-owned tables. api_audit_logs lives in siniestros-automation — read-only here."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class Project(Base):
    """A logical billing project (e.g. Siniestros Automation, Cotizaciones Fase II)."""

    __tablename__ = "portal_projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    budget_monthly: Mapped[float | None] = mapped_column(Float, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class CostConfig(Base):
    """Per-model price table. Editable from the UI. One active row per model_name."""

    __tablename__ = "portal_cost_config"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    model_name: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    # LLM pricing — USD per million tokens
    price_input_mtok: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    price_output_mtok: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Cache pricing — fraction of input price (Anthropic: read=0.1, creation=1.25)
    price_cache_read_mtok: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    price_cache_creation_mtok: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # OCR pricing — USD per 1000 pages (0 if not applicable)
    price_per_1k_pages: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class DevLicense(Base):
    """Fixed monthly dev license costs (Claude Max, etc.) — not in api_audit_logs."""

    __tablename__ = "portal_dev_licenses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    plan: Mapped[str] = mapped_column(String(60), nullable=False)
    # Precio de tarifa SIN impuestos, tal y como lo publica el proveedor.
    cost_monthly_usd: Mapped[float] = mapped_column(Float, nullable=False)
    # IVA aplicado en factura (21% en España). 0 para facturas con inversión del
    # sujeto pasivo, donde el proveedor no repercute IVA.
    tax_rate_pct: Mapped[float] = mapped_column(Float, default=21.0, nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(120), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    @property
    def cost_monthly_gross_usd(self) -> float:
        """Coste mensual con IVA — el importe que llega realmente en la factura."""
        return self.cost_monthly_usd * (1 + (self.tax_rate_pct or 0.0) / 100.0)
