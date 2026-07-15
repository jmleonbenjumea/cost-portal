import csv
import io
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cost_engine import calculate_row_cost
from app.database import get_db
from app.models import Project
from app.routers.dashboard import _load_prices
from app.templating import templates

router = APIRouter(prefix="/registro")

PAGE_SIZE = 50


@router.get("", response_class=HTMLResponse)
async def registro(
    request: Request,
    page: int = Query(1, ge=1),
    servicio: str = Query(""),
    operacion: str = Query(""),
    proyecto_id: str = Query(""),
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text

    prices = await _load_prices(db)
    offset = (page - 1) * PAGE_SIZE

    servicios = [
        r[0] for r in (await db.execute(
            text("SELECT DISTINCT servicio_externo FROM api_audit_logs WHERE servicio_externo IS NOT NULL ORDER BY 1")
        )).all()
    ]
    operaciones = [
        r[0] for r in (await db.execute(
            text("SELECT DISTINCT operacion FROM api_audit_logs WHERE operacion IS NOT NULL ORDER BY 1")
        )).all()
    ]
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()

    where_clauses = ["1=1"]
    params: dict = {"limit": PAGE_SIZE, "offset": offset}

    if servicio:
        where_clauses.append("a.servicio_externo = :servicio")
        params["servicio"] = servicio
    if operacion:
        where_clauses.append("a.operacion = :operacion")
        params["operacion"] = operacion
    if fecha_desde:
        try:
            dt = datetime.strptime(fecha_desde, "%Y-%m-%d").replace(tzinfo=UTC)
            where_clauses.append("a.timestamp >= :fecha_desde")
            params["fecha_desde"] = dt
        except ValueError:
            fecha_desde = ""
    if fecha_hasta:
        try:
            dt = datetime.strptime(fecha_hasta, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=UTC)
            where_clauses.append("a.timestamp <= :fecha_hasta")
            params["fecha_hasta"] = dt
        except ValueError:
            fecha_hasta = ""

    # Project filter: imputación por api_audit_logs.proyecto = Project.name (sin JOINs)
    selected_project = None
    if proyecto_id:
        selected_project = next((p for p in projects if p.id == proyecto_id), None)
        if selected_project:
            where_clauses.append("a.proyecto = :proyecto")
            params["proyecto"] = selected_project.name
        else:
            proyecto_id = ""

    where_sql = " AND ".join(where_clauses)
    from_sql = "api_audit_logs a"

    rows = (await db.execute(
        text(f"""
            SELECT a.id, a.conversation_id, a.timestamp, a.servicio_externo, a.operacion,
                   a.model_name, a.tokens_input, a.tokens_output,
                   a.tokens_cache_read, a.tokens_cache_creation, a.pages_processed,
                   a.pii_anonimizado, a.duracion_ms, a.resultado, a.codigo_error
            FROM {from_sql}
            WHERE {where_sql}
            ORDER BY a.timestamp DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    )).mappings().all()

    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total = (await db.execute(
        text(f"SELECT COUNT(*) FROM {from_sql} WHERE {where_sql}"),
        count_params,
    )).scalar() or 0

    enriched = []
    for row in rows:
        cost = calculate_row_cost(
            model_name=row["model_name"],
            tokens_input=row["tokens_input"],
            tokens_output=row["tokens_output"],
            tokens_cache_read=row["tokens_cache_read"],
            tokens_cache_creation=row["tokens_cache_creation"],
            pages_processed=row["pages_processed"],
            prices=prices,
        )
        enriched.append({**dict(row), "cost_usd": round(cost, 6)})

    return templates.TemplateResponse(request, "registro.html", {
        "rows": enriched,
        "page": page,
        "total": total,
        "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
        "servicio_filter": servicio,
        "operacion_filter": operacion,
        "proyecto_id_filter": proyecto_id,
        "fecha_desde_filter": fecha_desde,
        "fecha_hasta_filter": fecha_hasta,
        "servicios": servicios,
        "operaciones": operaciones,
        "projects": projects,
    })


@router.get("/csv")
async def registro_csv(
    servicio: str = Query(""),
    operacion: str = Query(""),
    proyecto_id: str = Query(""),
    fecha_desde: str = Query(""),
    fecha_hasta: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text

    prices = await _load_prices(db)
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()

    where_clauses = ["1=1"]
    params: dict = {}

    if servicio:
        where_clauses.append("a.servicio_externo = :servicio")
        params["servicio"] = servicio
    if operacion:
        where_clauses.append("a.operacion = :operacion")
        params["operacion"] = operacion
    if fecha_desde:
        try:
            params["fecha_desde"] = datetime.strptime(fecha_desde, "%Y-%m-%d").replace(tzinfo=UTC)
            where_clauses.append("a.timestamp >= :fecha_desde")
        except ValueError:
            pass
    if fecha_hasta:
        try:
            params["fecha_hasta"] = datetime.strptime(fecha_hasta, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59, tzinfo=UTC
            )
            where_clauses.append("a.timestamp <= :fecha_hasta")
        except ValueError:
            pass

    if proyecto_id:
        proj = next((p for p in projects if p.id == proyecto_id), None)
        if proj:
            where_clauses.append("a.proyecto = :proyecto")
            params["proyecto"] = proj.name

    where_sql = " AND ".join(where_clauses)
    from_sql = "api_audit_logs a"

    rows = (await db.execute(
        text(f"""
            SELECT a.id, a.timestamp, a.servicio_externo, a.operacion,
                   a.model_name, a.tokens_input, a.tokens_output,
                   a.tokens_cache_read, a.tokens_cache_creation, a.pages_processed,
                   a.duracion_ms, a.resultado, a.codigo_error, a.conversation_id
            FROM {from_sql}
            WHERE {where_sql}
            ORDER BY a.timestamp DESC
        """),
        params,
    )).mappings().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "timestamp", "servicio", "operacion", "modelo",
        "tokens_input", "tokens_output", "tokens_cache_read", "tokens_cache_creation",
        "paginas", "duracion_ms", "resultado", "codigo_error", "conversation_id", "coste_usd",
    ])
    for row in rows:
        cost = calculate_row_cost(
            model_name=row["model_name"],
            tokens_input=row["tokens_input"],
            tokens_output=row["tokens_output"],
            tokens_cache_read=row["tokens_cache_read"],
            tokens_cache_creation=row["tokens_cache_creation"],
            pages_processed=row["pages_processed"],
            prices=prices,
        )
        writer.writerow([
            row["id"], row["timestamp"], row["servicio_externo"], row["operacion"],
            row["model_name"], row["tokens_input"], row["tokens_output"],
            row["tokens_cache_read"], row["tokens_cache_creation"], row["pages_processed"],
            row["duracion_ms"], row["resultado"], row["codigo_error"], row["conversation_id"],
            round(cost, 6),
        ])

    filename = f"registro_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
