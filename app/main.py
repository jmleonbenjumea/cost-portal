from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.auth import require_auth
from app.config import settings
from app.database import Base, engine
from app.routers import config_router, dashboard, proyectos, registro

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_default_prices()
    await _seed_initial_data()
    logger.info("cost_portal.started", port=settings.portal_port)
    yield


async def _seed_default_prices() -> None:
    """Insert default price rows if cost_config table is empty."""
    from sqlalchemy import func, select

    from app.cost_engine import DEFAULT_PRICES
    from app.database import AsyncSessionLocal
    from app.models import CostConfig

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(CostConfig))).scalar()
        if count and count > 0:
            return
        for model_name, p in DEFAULT_PRICES.items():
            provider = "ANTHROPIC" if "claude" in model_name else (
                "OPENAI" if "gpt" in model_name else "AZURE_DOC_INTEL"
            )
            db.add(CostConfig(
                model_name=model_name,
                provider=provider,
                price_input_mtok=p.price_input_mtok,
                price_output_mtok=p.price_output_mtok,
                price_cache_read_mtok=p.price_cache_read_mtok,
                price_cache_creation_mtok=p.price_cache_creation_mtok,
                price_per_1k_pages=p.price_per_1k_pages,
            ))
        await db.commit()
        logger.info("cost_portal.prices_seeded")


async def _seed_initial_data() -> None:
    """Seed the Siniestros Automation project and dev licenses if tables are empty."""
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models import DevLicense, Project

    async with AsyncSessionLocal() as db:
        # ── Proyecto Siniestros Automation ────────────────────────────────────
        # La imputación de costes se hace por api_audit_logs.proyecto = Project.name.
        proj_count = (await db.execute(select(func.count()).select_from(Project))).scalar()
        if not proj_count:
            db.add(Project(
                name="Siniestros Automation",
                description="Apertura automática de siniestros de impago de alquiler",
                color="#6366f1",
                budget_monthly=100.0,
            ))
            logger.info("cost_portal.project_seeded", name="Siniestros Automation")
        else:
            # Rename legacy "Siniestros Fase I" → "Siniestros Automation" (idempotente;
            # también lo hace la migración 0003, esto cubre instalaciones que sembraron
            # antes de la migración).
            legacy = (await db.execute(
                select(Project).where(Project.name == "Siniestros Fase I")
            )).scalar_one_or_none()
            if legacy:
                legacy.name = "Siniestros Automation"
                logger.info("cost_portal.project_renamed", name="Siniestros Automation")

        # ── Licencias de desarrollo ───────────────────────────────────────────
        lic_count = (await db.execute(select(func.count()).select_from(DevLicense))).scalar()
        if not lic_count:
            licenses = [
                DevLicense(
                    name="Claude Max 5x",
                    provider="Anthropic",
                    plan="Max 5x",
                    cost_monthly_usd=100.00,
                    notes="Desarrolladores principales. Amortizable entre todos los proyectos activos.",
                ),
                DevLicense(
                    name="Power Automate Premium",
                    provider="Microsoft",
                    plan="Per User (1 usuario)",
                    cost_monthly_usd=15.00,
                    notes="Trigger email → webhook POST. Integración nativa Office 365.",
                ),
            ]
            for lic in licenses:
                db.add(lic)
            logger.info("cost_portal.licenses_seeded", count=len(licenses))

        await db.commit()


app = FastAPI(title="Benjumea · Control de Gastos IA", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

_auth = [Depends(require_auth)]

app.include_router(dashboard.router, dependencies=_auth)
app.include_router(registro.router, dependencies=_auth)
app.include_router(proyectos.router, dependencies=_auth)
app.include_router(config_router.router, dependencies=_auth)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.portal_port, reload=True)
