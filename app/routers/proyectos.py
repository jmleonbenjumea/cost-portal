from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cost_engine import calculate_row_cost
from app.database import get_db
from app.models import Project
from app.routers.dashboard import _load_prices
from app.templating import templates

router = APIRouter(prefix="/proyectos")


@router.get("", response_class=HTMLResponse)
async def proyectos(request: Request, db: AsyncSession = Depends(get_db)):
    prices = await _load_prices(db)
    projects = (await db.execute(select(Project).order_by(Project.name))).scalars().all()

    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    project_stats = []
    for proj in projects:
        # Las filas se imputan por api_audit_logs.proyecto = Project.name (sin JOINs).
        all_rows = (await db.execute(
            text("""
                SELECT a.model_name, a.tokens_input, a.tokens_output,
                       a.tokens_cache_read, a.tokens_cache_creation, a.pages_processed,
                       DATE(a.timestamp AT TIME ZONE 'UTC') AS day
                FROM api_audit_logs a
                WHERE a.resultado = 'OK' AND a.proyecto = :proyecto
                ORDER BY a.timestamp
            """),
            {"proyecto": proj.name},
        )).mappings().all()
        month_rows = (await db.execute(
            text("""
                SELECT a.model_name, a.tokens_input, a.tokens_output,
                       a.tokens_cache_read, a.tokens_cache_creation, a.pages_processed
                FROM api_audit_logs a
                WHERE a.resultado = 'OK' AND a.proyecto = :proyecto
                  AND a.timestamp >= :month_start
            """),
            {"proyecto": proj.name, "month_start": month_start},
        )).mappings().all()

        total_cost = 0.0
        total_calls = len(all_rows)
        daily: dict[str, float] = {}
        for row in all_rows:
            cost = calculate_row_cost(
                model_name=row["model_name"],
                tokens_input=row["tokens_input"],
                tokens_output=row["tokens_output"],
                tokens_cache_read=row["tokens_cache_read"],
                tokens_cache_creation=row["tokens_cache_creation"],
                pages_processed=row["pages_processed"],
                prices=prices,
            )
            total_cost += cost
            day = str(row["day"])
            daily[day] = daily.get(day, 0.0) + cost

        month_cost = sum(
            calculate_row_cost(
                model_name=r["model_name"],
                tokens_input=r["tokens_input"],
                tokens_output=r["tokens_output"],
                tokens_cache_read=r["tokens_cache_read"],
                tokens_cache_creation=r["tokens_cache_creation"],
                pages_processed=r["pages_processed"],
                prices=prices,
            )
            for r in month_rows
        )

        chart_labels = sorted(daily.keys())
        chart_values = [round(daily[d], 4) for d in chart_labels]

        budget = proj.budget_monthly or 0
        budget_pct = round(min(month_cost / budget * 100, 100), 1) if budget > 0 else None

        project_stats.append({
            "id": proj.id,
            "name": proj.name,
            "description": proj.description,
            "color": proj.color,
            "total_cost": round(total_cost, 4),
            "month_cost": round(month_cost, 4),
            "total_calls": total_calls,
            "budget_monthly": budget,
            "budget_pct": budget_pct,
            "chart_labels": chart_labels,
            "chart_values": chart_values,
            "month_name": now.strftime("%B %Y"),
        })

    return templates.TemplateResponse(request, "proyectos.html", {
        "projects": project_stats,
    })
