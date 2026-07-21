"""Integration-style tests for HTTP routes using an in-memory SQLite DB."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

# api_audit_logs es externa (la escribe siniestros-automation); aquí la creamos a
# mano para los tests porque no tiene modelo en cost-portal (lectura por SQL crudo).
_CREATE_AUDIT_LOGS = """
CREATE TABLE api_audit_logs (
    id TEXT PRIMARY KEY,
    proyecto TEXT,
    conversation_id TEXT,
    timestamp TIMESTAMP NOT NULL,
    servicio_externo TEXT NOT NULL,
    operacion TEXT NOT NULL,
    model_name TEXT,
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_cache_read INTEGER,
    tokens_cache_creation INTEGER,
    pages_processed INTEGER,
    pii_anonimizado BOOLEAN NOT NULL DEFAULT 0,
    entidades_pii_count INTEGER,
    duracion_ms INTEGER NOT NULL,
    resultado TEXT NOT NULL,
    codigo_error TEXT,
    proveedor_region TEXT
)
"""


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(_CREATE_AUDIT_LOGS))
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    # En dev (ENVIRONMENT por defecto = development) el middleware `portal_auth` no
    # exige autenticación, así que no hace falta inyectar credenciales en los tests.

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_dashboard_returns_200(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert "Dashboard" in response.text


@pytest.mark.asyncio
async def test_dashboard_month_filter(client):
    response = await client.get("/?month=2026-01")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_dashboard_invalid_month_falls_back(client):
    response = await client.get("/?month=not-a-date")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_registro_returns_200(client):
    response = await client.get("/registro")
    assert response.status_code == 200
    assert "Registro" in response.text


@pytest.mark.asyncio
async def test_registro_csv_returns_csv(client):
    response = await client.get("/registro/csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    # Formato europeo: separador `;` y BOM UTF-8 para que Excel-ES lo abra bien.
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert "id;timestamp" in response.text
    assert "coste_eur;coste_usd;tipo_cambio_usd_eur" in response.text


@pytest.mark.asyncio
async def test_proyectos_returns_200(client):
    response = await client.get("/proyectos")
    assert response.status_code == 200


_INSERT_AUDIT = """
INSERT INTO api_audit_logs
    (id, proyecto, conversation_id, timestamp, servicio_externo, operacion,
     model_name, tokens_input, tokens_output, pii_anonimizado, duracion_ms, resultado)
VALUES
    (:id, :proyecto, NULL, :ts, 'ANTHROPIC', 'CLASSIFY',
     'claude-sonnet-4-6', 100, 50, 0, 10, 'OK')
"""


@pytest.mark.asyncio
async def test_registro_filters_by_proyecto(client, db_engine):
    """Una sola api_audit_logs compartida: el filtro discrimina por la columna proyecto."""
    from datetime import UTC, datetime

    from app.models import Project

    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as s:
        proj = Project(name="Proyecto A", color="#111111")
        s.add(proj)
        await s.flush()
        proj_id = proj.id
        ts = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
        await s.execute(text(_INSERT_AUDIT), {"id": "row-a", "proyecto": "Proyecto A", "ts": ts})
        await s.execute(text(_INSERT_AUDIT), {"id": "row-b", "proyecto": "Otro Proyecto", "ts": ts})
        await s.commit()

    # Sin filtro: ambas filas (toda la info de todos los proyectos vive en la misma tabla)
    full = await client.get("/registro/csv")
    assert "row-a" in full.text and "row-b" in full.text

    # Filtrado por Proyecto A: solo su fila, vía a.proyecto = Project.name (sin JOINs)
    filtered = await client.get(f"/registro/csv?proyecto_id={proj_id}")
    assert "row-a" in filtered.text
    assert "row-b" not in filtered.text


@pytest.mark.asyncio
async def test_config_returns_200(client):
    response = await client.get("/config")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_auth_required_in_production(monkeypatch):
    """En producción y sin credenciales, las rutas protegidas devuelven 401.

    El middleware `portal_auth` solo exige auth cuando NO es desarrollo; se fuerza
    `environment=production` para ejercitar la puerta cerrada. El 401 se emite antes
    de tocar la BD, así que no hace falta override de get_db.
    """
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "environment", "production")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_upsert_project_creates_project(client):
    response = await client.post("/config/proyectos/upsert", data={
        "project_id": "",
        "name": "Test Project",
        "description": "desc",
        "color": "#ff0000",
        "budget_monthly": "50",
    })
    assert response.status_code in (200, 303)

    config_page = await client.get("/config")
    assert "Test Project" in config_page.text


@pytest.mark.asyncio
async def test_upsert_price(client):
    response = await client.post("/config/precios/upsert", data={
        "model_name": "test-model",
        "provider": "OPENAI",
        "price_input_mtok": "1.0",
        "price_output_mtok": "2.0",
        "price_cache_read_mtok": "0.1",
        "price_cache_creation_mtok": "1.25",
        "price_per_1k_pages": "0",
        "notes": "",
    })
    assert response.status_code in (200, 303)
