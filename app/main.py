import base64
import binascii
import secrets
from contextlib import asynccontextmanager

import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.routers import auth, config_router, dashboard, proyectos, registro

logger = structlog.get_logger(__name__)

# Rutas exentas de la auth de panel: todo el flujo de login (/login y /auth/*, que no
# pueden requerir sesión para funcionar) y los estáticos (logo/css de la pantalla de login).
_AUTH_EXEMPT_EXACT = {"/login"}
_AUTH_EXEMPT_PREFIX = ("/auth", "/static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_default_prices()
    await _seed_initial_data()
    logger.info("cost_portal.started", port=settings.portal_port, sso=settings.portal_sso_enabled)
    yield


async def _seed_default_prices() -> None:
    """Ensure every model in DEFAULT_PRICES has a row in cost_config.

    Idempotente por ``model_name``: inserta solo los que falten (p.ej. modelos nuevos
    como ``gpt-5-mini`` o ``prebuilt-layout``) y NO pisa los precios que ya se hayan
    ajustado en la UI. Sin esto, un modelo nuevo aparecía en el dashboard sin precio
    asociado (coste 0) hasta darlo de alta a mano.
    """
    from sqlalchemy import select

    from app.cost_engine import DEFAULT_PRICES
    from app.database import AsyncSessionLocal
    from app.models import CostConfig

    async with AsyncSessionLocal() as db:
        existing = set((await db.execute(select(CostConfig.model_name))).scalars().all())
        added = 0
        for model_name, p in DEFAULT_PRICES.items():
            if model_name in existing:
                continue
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
            added += 1
        if added:
            await db.commit()
            logger.info("cost_portal.prices_seeded", added=added)


# Proyectos base. La imputación de costes se hace por api_audit_logs.proyecto =
# Project.name, así que estos nombres deben coincidir EXACTAMENTE con el PROYECTO_NOMBRE
# de cada app (Siniestros Automation y el clasificador-correos → "Mailhandler").
_DEFAULT_PROJECTS = [
    ("Siniestros Automation", "Apertura automática de siniestros de impago de alquiler",
     "#6366f1", 100.0),
    ("Mailhandler", "Clasificador/triaje de correos entrantes de la correduría",
     "#f08a12", 20.0),
]


async def _seed_initial_data() -> None:
    """Ensure the base projects and dev licenses exist (idempotente por nombre)."""
    from sqlalchemy import func, select

    from app.database import AsyncSessionLocal
    from app.models import DevLicense, Project

    async with AsyncSessionLocal() as db:
        # ── Proyectos ─────────────────────────────────────────────────────────
        existing = {
            p.name: p for p in (await db.execute(select(Project))).scalars().all()
        }
        # Rename legacy "Siniestros Fase I" → "Siniestros Automation" (idempotente;
        # también lo hace la migración 0003, esto cubre instalaciones que sembraron
        # antes de la migración).
        legacy = existing.get("Siniestros Fase I")
        if legacy and "Siniestros Automation" not in existing:
            legacy.name = "Siniestros Automation"
            existing["Siniestros Automation"] = existing.pop("Siniestros Fase I")
            logger.info("cost_portal.project_renamed", name="Siniestros Automation")
        # Alta de los proyectos que falten (p.ej. "Mailhandler" en instalaciones ya
        # sembradas antes de que existiera el clasificador-correos).
        for name, description, color, budget in _DEFAULT_PROJECTS:
            if name not in existing:
                db.add(Project(
                    name=name, description=description, color=color, budget_monthly=budget,
                ))
                logger.info("cost_portal.project_seeded", name=name)

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


def _basic_auth_ok(request: Request) -> bool:
    """Validate the HTTP Basic header against portal_user/portal_password (break-glass)."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        user, _, pwd = base64.b64decode(header[6:]).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    return (
        secrets.compare_digest(user, settings.portal_user)
        and bool(settings.portal_password)
        and secrets.compare_digest(pwd, settings.portal_password)
    )


@app.middleware("http")
async def portal_auth(request: Request, call_next):
    """Protege el panel. Exime el flujo de login (/login, /auth/*) y los estáticos.

    En desarrollo no se exige (comodidad local). En producción:
      - Si ``portal_sso_enabled``: requiere sesión SSO de Microsoft (o break-glass HTTP
        Basic). Navegaciones de navegador sin sesión → redirección a /login; el resto → 401.
      - Si no: HTTP Basic con ``portal_user``/``portal_password`` (comportamiento anterior).
    """
    path = request.url.path
    exempt = path in _AUTH_EXEMPT_EXACT or path.startswith(_AUTH_EXEMPT_PREFIX)
    if settings.is_development or exempt:
        return await call_next(request)

    # 1) Sesión SSO válida.
    if settings.portal_sso_enabled and request.session.get("user"):
        return await call_next(request)

    # 2) Break-glass HTTP Basic.
    if _basic_auth_ok(request):
        return await call_next(request)

    # 3) No autorizado. Con SSO, las navegaciones de navegador van al login; el resto, 401.
    if settings.portal_sso_enabled and "text/html" in request.headers.get("Accept", ""):
        return RedirectResponse("/login", status_code=302)
    headers = {} if settings.portal_sso_enabled else {"WWW-Authenticate": 'Basic realm="Benjumea"'}
    return JSONResponse(status_code=401, content={"detail": "No autorizado"}, headers=headers)


# Cookie de sesión firmada (para el SSO). Se instala SIEMPRE para que ``request.session``
# exista; con SSO desactivado la sesión no se usa. Debe quedar como middleware MÁS EXTERNO
# que ``portal_auth`` (se añade después), para que la sesión esté disponible en él. El
# secreto debe ser estable entre workers cuando hay SSO (de ahí el fail-fast en config);
# sin SSO un secreto efímero por proceso es irrelevante.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or secrets.token_urlsafe(32),
    https_only=not settings.is_development,
    same_site="lax",
    max_age=8 * 60 * 60,
)

app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(registro.router)
app.include_router(proyectos.router)
app.include_router(config_router.router)


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.portal_port, reload=True)
